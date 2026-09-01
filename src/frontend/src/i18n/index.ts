import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import de from "./locales/de/common.json";
import en from "./locales/en/common.json";

export const SUPPORTED_LANGUAGES = ["en", "de"] as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { common: en },
      de: { common: de },
    },
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LANGUAGES,
    defaultNS: "common",
    interpolation: { escapeValue: false },
  });

export default i18n;
