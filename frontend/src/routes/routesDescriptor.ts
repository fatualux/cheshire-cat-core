import { AppFeatures } from '@models/AppFeatures'

export interface RoutesDescriptor {
  path: string
  label: string
  guard?: AppFeatures
  external?: boolean
}

const routesDescriptor = {
  home: { path: '/', label: 'Home' },
  settings: { path: '/settings', label: 'Settings', guard: AppFeatures.Settings },
  llm: { path: '/settings/llm', label: 'Language model provider', guard: AppFeatures.Settings },
  plugins: { path: '/plugins', label: 'Plugins', guard: AppFeatures.Plugins },
  documentation: { path: 'https://www.google.com', label: 'Documentation' }
} satisfies Record<string, RoutesDescriptor>

export default routesDescriptor
