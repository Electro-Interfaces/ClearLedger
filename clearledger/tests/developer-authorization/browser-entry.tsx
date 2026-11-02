// Изолированный локальный стенд: настоящий router/AuthProvider/login/page, без main.tsx
// (PWA, scheduler и миграция localStorage не относятся к проверке согласия).
import { createRoot } from 'react-dom/client'
import App from '../../src/App'
import '../../src/index.css'

createRoot(document.getElementById('root')!).render(<App />)
