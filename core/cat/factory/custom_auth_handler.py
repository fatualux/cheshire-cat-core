
import jwt
import httpx
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pydantic import BaseModel

from fastapi import (
    WebSocket,
    Request,
    HTTPException
)
#from fastapi.security import OAuth2AuthorizationCodeBearer

from keycloak import KeycloakOpenID

from cat.env import get_env
from cat.log import log


class BaseAuthHandler(ABC): # TODOAUTH: pydantic model?
    """
    Base class to build custom Auth systems that will live alongside core auth.
    Methods `is_http_allowed` and `is_ws_allowed`
    MUST be implemented by subclasses.
    """

    async def _is_http_allowed(self, request: Request):

        env_key_is_correct = False
        
        # Protect http endpoints via CCAT_API_KEY env variable.
        environment_api_key = get_env("CCAT_API_KEY")
        
        if environment_api_key is None:
            # env not set, delegate to custom auth
            env_key_is_correct = True
        else:
            # env is set, must be same as header `access_token`
            env_key_is_correct = request.headers.get("access_token") == environment_api_key
        
        return env_key_is_correct and self.is_http_allowed(request)

    async def _is_ws_allowed(self, websocket: WebSocket):

        env_key_is_correct = False
        
        # Protect websockets via CCAT_API_KEY_WS env variable.
        environment_api_key = get_env("CCAT_API_KEY_WS")
        
        if environment_api_key is None:
            # env not set, delegate to custom auth
            env_key_is_correct = True
        else:
            # env is set, must be same as query param `access_token`
            env_key_is_correct = websocket.query_params.get("access_token") == environment_api_key
        
        return env_key_is_correct and self.is_ws_allowed(websocket)
    

    @abstractmethod
    async def is_http_allowed(self, request: Request):
        pass

    @abstractmethod
    async def is_ws_allowed(self, websocket: WebSocket):
        pass


# Internal Auth, used as a standard for the admin panel and other community clients.
class CoreAuthHandler(BaseAuthHandler):

    # TODOAUTH: this cannot stay in the code
    # TODOAUTH: use CCAT_API_KEY?
    secret_key = "sfdjgnsiobesiubib54ku3vku6v553kuv6uv354uvk5yuvtku5"
    algorithm = "HS256"
    access_token_expire_minutes = 30

    async def get_full_authorization_url(self, request: Request):

        # Identity Provider login page
        auth_url = "http://localhost:1865/auth/core_login"
        return auth_url
    

    async def get_token_from_identity_provider(self, request: Request):

        # when no external identity provider is present, core issues the token directly
        #  based on a key given in the admin # TODOAUTH

        form_data = await request.form()
        log.warning(form_data)


        to_encode = dict(form_data).copy()
        expire = datetime.utcnow() + timedelta(self.access_token_expire_minutes)
        del to_encode["password"]
        to_encode["exp"] = expire
        # TODOAUTH: add issuer and redirect_uri (and verify them when a token is validated)

        return jwt.encode(
            to_encode,
            self.secret_key,
            algorithm=self.algorithm
        )


    async def verify_token(self, token: str) -> dict:

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            pass
        except jwt.InvalidTokenError:
            pass


        #TODOAUTH: move exception out, this method should return be a simple boolean
        raise HTTPException(status_code=403, detail="Token verification failed")

    async def is_http_allowed(self, request: Request):

        # check "Authorization" header
        auth_header = request.headers.get("Authorization")
        if auth_header is None or not auth_header.startswith("Bearer "):
            return False
        
        # verify token
        token = auth_header.split(" ")[1]
        return await self.verify_token(token)

    async def is_ws_allowed(self, websocket: WebSocket):

        # verify token
        token = websocket.query_params.get("token")
        return await self.verify_token(token)


class KeycloackAuthHandler(BaseAuthHandler):

    def __init__(self):
        
        # login panel
        # http://localhost:8080/realms/gatto/account

        # direct token! (implicit mode)
        # http://localhost:8080/realms/gatto/protocol/openid-connect/auth?client_id=gattoclient&redirect_uri=http://localhost:1865/admin&response_type=token

        # Keycloak info
        # http://localhost:8080/realms/gatto
        # http://localhost:8080/realms/gatto/.well-known/openid-configuration
        
        self.client_id = "gattoclient"
        self.realm_name = "gatto"
        self.server_url = "http://localhost:8080/" # TODOAUTH should use IP if out of compose
        if self.server_url[-1] == "/":
            self.server_url = self.server_url[:-1]
        self.authorization_url = f"{self.server_url}/realms/gatto/protocol/openid-connect/auth"
        self.token_url = f"{self.server_url}/realms/gatto/protocol/openid-connect/token"
        self.redirect_uri = "http://localhost:1865/auth/access_code"
        
        #self.oauth2_scheme = OAuth2AuthorizationCodeBearer(
            # URL to the login panel
        #    authorizationUrl=self.authorization_url,
            # The URL to obtain the OAuth2 token
        #    tokenUrl=self.token_url,
            # Where to obtain a new token
        #    refreshUrl="", # TODOAUTH
        #    scheme_name="OAuth2 for da Cat",
        #    auto_error=True,
        #)

        # This actually does the auth checks
        self.keycloak_openid = KeycloakOpenID(
            server_url=self.server_url,
            client_id=self.client_id,
            realm_name=self.realm_name,
            client_secret_key="",
            verify=True
        )

        #config_well_known = self.keycloak_openid.well_known()
        #log.error(config_well_known)

    async def get_full_authorization_url(self, request):

        # IP login page (query params are essential to redirect the "access code" back to core)
        auth_url = self.keycloak_openid.auth_url(
            redirect_uri=self.redirect_uri
        )
        return auth_url

    async def get_token_from_identity_provider(self, request: Request):
        code = request.query_params.get("code")

        log.warning(code)
        if not code:
            raise HTTPException(status_code=400, detail="Authorization code was not given from the Identity Provider")
        
        try:
            access_token = self.keycloak_openid.token(
                grant_type='authorization_code',
                code=code,
                redirect_uri=self.redirect_uri
            )
            return access_token["access_token"]
        except:
            log.error("Error during code to token request")
            raise HTTPException(status_code=403, detail="Authorization token not granted from the Identity Provider")
    
    async def verify_token(self, token: str) -> dict:
        try:
            token_info = self.keycloak_openid.introspect(token)
            if not token_info.get("active"):
                raise HTTPException(status_code=403, detail="Invalid token")
            return token_info
        except Exception as e:
            raise HTTPException(status_code=403, detail="Token verification failed") 

    async def is_http_allowed(self, request: Request):
        return True

    async def is_ws_allowed(self, websocket: WebSocket):
        return True


# TODOAUTH: create simple custom AuthHandler
"""
# Set http and ws keys directly into the admin settings
class AuthApiKey(BaseAuthHandler):

    def __init__(self, api_key_http=None, api_key_ws=None):
        self.api_key_http = api_key_http
        self.api_key_ws = api_key_ws

    def is_http_allowed(self, request: Request):
        return request.headers.get("access_token") == self.api_key_http

    def is_ws_allowed(self, websocket: WebSocket):
        return websocket.query_params.get("access_token") == self.api_key_ws
"""