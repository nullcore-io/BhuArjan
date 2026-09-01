import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

// en + hi from day one (Docs/Frontend.md §9). hi grows as screens land.
const resources = {
  en: {
    translation: {
      appName: 'BhuArjan',
      appNameHi: 'भू-अर्जन',
      tagline: 'National Land Acquisition & Management System',
      login: 'Sign in',
      nationalDashboard: 'National Dashboard',
      projects: 'Projects',
      alerts: 'Alerts',
      publicStatus: 'Public Status',
      caseLedger: 'Case Ledger',
      recordEvent: 'Record Event',
    },
  },
  hi: {
    translation: {
      appName: 'भू-अर्जन',
      appNameHi: 'BhuArjan',
      tagline: 'राष्ट्रीय भूमि अर्जन एवं प्रबंधन प्रणाली',
      login: 'साइन इन',
      nationalDashboard: 'राष्ट्रीय डैशबोर्ड',
      projects: 'परियोजनाएँ',
      alerts: 'अलर्ट',
      publicStatus: 'सार्वजनिक स्थिति',
      caseLedger: 'प्रकरण खाता',
      recordEvent: 'घटना दर्ज करें',
    },
  },
}

i18n.use(initReactI18next).init({
  resources,
  lng: localStorage.getItem('bhuarjan.lang') || 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
