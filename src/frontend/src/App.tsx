import HomePage from './pages/HomePage.tsx'
import { LoginPage } from './pages/LoginPage.tsx'

function App() {
  const path = window.location.pathname
  if (path === '/login') {
    return <LoginPage />
  }
  return <HomePage />
}

export default App
