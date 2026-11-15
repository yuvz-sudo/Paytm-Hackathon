// Languages the merchant can pick. Same list as backend/app/languages.py.
// [code, native name, English name, example question, browser speech code (fallback only)]
export const LANGUAGES: [string, string, string, string, string][] = [
  ["hinglish", "Hinglish", "Hinglish", "Kal ki sales kitni thi?", "hi-IN"],
  ["hi", "हिन्दी", "Hindi", "कल की बिक्री कितनी थी?", "hi-IN"],
  ["en", "English", "English", "What were yesterday’s sales?", "en-IN"],
  ["bn", "বাংলা", "Bengali", "গতকাল কত বিক্রি হয়েছে?", "bn-IN"],
  ["gu", "ગુજરાતી", "Gujarati", "ગઈકાલે કેટલું વેચાણ થયું?", "gu-IN"],
  ["kn", "ಕನ್ನಡ", "Kannada", "ನಿನ್ನೆ ಎಷ್ಟು ಮಾರಾಟ ಆಯಿತು?", "kn-IN"],
  ["ml", "മലയാളം", "Malayalam", "ഇന്നലെ എത്ര വിൽപ്പന നടന്നു?", "ml-IN"],
  ["mr", "मराठी", "Marathi", "काल किती विक्री झाली?", "mr-IN"],
  ["od", "ଓଡ଼ିଆ", "Odia", "ଗତକାଲି କେତେ ବିକ୍ରି ହେଲା?", "or-IN"],
  ["pa", "ਪੰਜਾਬੀ", "Punjabi", "ਕੱਲ੍ਹ ਕਿੰਨੀ ਵਿਕਰੀ ਹੋਈ?", "pa-IN"],
  ["ta", "தமிழ்", "Tamil", "நேற்று எவ்வளவு விற்பனை ஆனது?", "ta-IN"],
  ["te", "తెలుగు", "Telugu", "నిన్న ఎంత అమ్మకం జరిగింది?", "te-IN"],
];

export const BROWSER_SPEECH: Record<string, string> = Object.fromEntries(LANGUAGES.map((l) => [l[0], l[4]]));
export const nativeName = (code: string) => LANGUAGES.find((l) => l[0] === code)?.[1] ?? code;
// The UI is shown in English for these (Hinglish is a speaking style; replies still follow it).
export const UI_IN_ENGLISH = new Set(["en", "hinglish"]);
