import { Outlet, useLocation } from 'react-router-dom'
import { AppHeader } from './AppHeader'
import './layout.css'

export function AppShell() {
  const location = useLocation()
  const isConsole = location.pathname === '/stories/new' || /^\/stories\/[^/]+\/(workspace|reference)$/.test(location.pathname)

  return (
    <div className={`app-shell ${isConsole ? 'app-shell--console' : ''}`}>
      <AppHeader />
      <main className='app-shell__main'>
        <Outlet />
      </main>
    </div>
  )
}
