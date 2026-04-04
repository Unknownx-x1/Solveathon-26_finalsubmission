(function () {
  const STORAGE_KEY = "portal_language";
  const SUPPORTED = { en: "English", ta: "தமிழ்" };
  let currentLanguage = localStorage.getItem(STORAGE_KEY) || "en";
  const originalTextMap = new WeakMap();
  const observerConfig = { childList: true, subtree: true };
  let isApplying = false;

  const REPLACEMENTS = [
    [/\bStudent Portal\b/gi, "மாணவர் போர்டல்"],
    [/\bStaff Portal\b/gi, "பணியாளர் போர்டல்"],
    [/\bDashboard\b/gi, "டாஷ்போர்டு"],
    [/\bLaundry Status\b/gi, "சலவை நிலை"],
    [/\bToken Generation\b/gi, "டோக்கன் உருவாக்கம்"],
    [/\bSchedule\b/gi, "அட்டவணை"],
    [/\bNotifications\b/gi, "அறிவிப்புகள்"],
    [/\bComplaints\b/gi, "புகார்கள்"],
    [/\bBucket\b/gi, "பக்கெட்"],
    [/\bBucket Requests\b/gi, "பக்கெட் கோரிக்கைகள்"],
    [/\bLost & Found\b/gi, "தொலைந்தவை & கண்டெடுக்கப்பட்டவை"],
    [/\bBucket\b/gi, "பக்கெட்"],
    [/\bBucket Requests\b/gi, "பக்கெட் கோரிக்கைகள்"],
    [/\bPreference\b/gi, "விருப்பம்"],
    [/\bLanguage\b/gi, "மொழி"],
    [/\bLogout\b/gi, "வெளியேறு"],
    [/\bExit Portal\b/gi, "போர்டலில் இருந்து வெளியேறு"],
    [/\bLaundry Manager\b/gi, "சலவை மேலாளர்"],
    [/\bAdministrator\b/gi, "நிர்வாகி"],
    [/\bStatus Update\b/gi, "நிலை புதுப்பிப்பு"],
    [/\bLaundry History\b/gi, "சலவை வரலாறு"],
    [/\bBooking Board\b/gi, "முன்பதிவு பலகை"],
    [/\bAnnouncements\b/gi, "அறிவிப்புகள்"],
    [/\bStudents\b/gi, "மாணவர்கள்"],
    [/\bBookings\b/gi, "முன்பதிவுகள்"],
    [/\bSubmitted\b/gi, "சமர்ப்பிக்கப்பட்டது"],
    [/\bWashing\b/gi, "துவைக்கப்படுகிறது"],
    [/\bReady\b/gi, "தயார்"],
    [/\bPicked Up\b/gi, "பெற்றுக்கொள்ளப்பட்டது"],
    [/Cancelled Booking/gi, "ரத்து செய்யப்பட்ட முன்பதிவு"],
    [/\bBooked\b/gi, "முன்பதிவு செய்யப்பட்டது"],
    [/Cancelled Booking/gi, "ரத்து செய்யப்பட்ட முன்பதிவு"],
    [/\bPending\b/gi, "நிலுவையில்"],
    [/\bQuick Actions\b/gi, "விரைவு செயல்கள்"],
    [/\bTrack Laundry\b/gi, "சலவையை கண்காணிக்க"],
    [/\bReport Issue\b/gi, "பிரச்சினையை தெரிவிக்க"],
    [/\bStudent Login\b/gi, "மாணவர் உள்நுழைவு"],
    [/Enter your registration number/gi, "உங்கள் பதிவு எண்ணை உள்ளிடவும்"],
    [/\bRegistration number\b/gi, "பதிவு எண்"],
    [/\bRegistration Number\b/gi, "பதிவு எண்"],
    [/\bRegistration No\b/gi, "பதிவு எண்"],
    [/\bContinue\b/gi, "தொடரவும்"],
    [/Back to home/gi, "முகப்பிற்கு திரும்ப"],
    [/Signing in…/gi, "உள்நுழைகிறது…"],
    [/Please enter your registration number\./gi, "தயவு செய்து உங்கள் பதிவு எண்ணை உள்ளிடவும்."],
    [/Registration number not found\./gi, "பதிவு எண் கிடைக்கவில்லை."],
    [/Something went wrong\. Please try again\./gi, "ஏதோ தவறு ஏற்பட்டது. மீண்டும் முயற்சிக்கவும்."],
    [/\bYour Active Booking\b/gi, "உங்கள் செயலில் உள்ள முன்பதிவு"],
    [/\bScheduled Date\b/gi, "முன்பதிவு தேதி"],
    [/\bTime Slot\b/gi, "நேர இடைவெளி"],
    [/\bBook a Laundry Slot\b/gi, "சலவை நேரத்தை முன்பதிவு செய்க"],
    [/\bSelect Date\b/gi, "தேதியை தேர்வு செய்க"],
    [/\bMonthly Usage\b/gi, "மாதாந்திர பயன்பாடு"],
    [/\bAvailable Time Slots\b/gi, "கிடைக்கும் நேரங்கள்"],
    [/\bConfirm Booking\b/gi, "முன்பதிவை உறுதிப்படுத்து"],
    [/\bBooking History\b/gi, "முன்பதிவு வரலாறு"],
    [/Manage your past and upcoming laundry slots/gi, "உங்கள் கடந்த மற்றும் வரவிருக்கும் சலவை நேரங்களை நிர்வகிக்கவும்"],
    [/\bLaundry Status\b/gi, "சலவை நிலை"],
    [/Track your batches by current stage/gi, "உங்கள் தொகுப்புகளின் தற்போதைய நிலையைப் பாருங்கள்"],
    [/\bProcessing\b/gi, "செயல்பாட்டில்"],
    [/\bCompleted\b/gi, "முடிந்தது"],
    [/Submitted, washing, or ready for pickup/gi, "சமர்ப்பிக்கப்பட்டது, துவைக்கப்படுகிறது, அல்லது பெற தயாராக உள்ளது"],
    [/No pending batches\./gi, "நிலுவையில் எந்த தொகுப்பும் இல்லை."],
    [/Nothing in processing\./gi, "செயல்பாட்டில் எதுவும் இல்லை."],
    [/No completed laundry yet\./gi, "முடிந்த சலவை இதுவரை இல்லை."],
    [/Mark as Picked Up/gi, "பெற்றுக்கொண்டதாக குறி"],
    [/Create New Booking/gi, "புதிய முன்பதிவு உருவாக்கு"],
    [/One chance is over due to missed date\./gi, "தேதி தவறியதால் ஒரு வாய்ப்பு குறைக்கப்பட்டது."],
    [/No cancelled bookings\./gi, "ரத்து செய்யப்பட்ட முன்பதிவுகள் இல்லை."],
    [/Create Urgent Request/gi, "அவசர கோரிக்கை உருவாக்கு"],
    [/Send Request/gi, "கோரிக்கையை அனுப்பு"],
    [/No bucket requests yet\./gi, "இன்னும் பக்கெட் கோரிக்கைகள் இல்லை."],
    [/\bAccept\b/gi, "ஏற்கவும்"],
    [/\bDecline\b/gi, "நிராகரி"],
    [/Create New Booking/gi, "புதிய முன்பதிவு உருவாக்கு"],
    [/One chance is over due to missed date\./gi, "தேதி தவறியதால் ஒரு வாய்ப்பு குறைக்கப்பட்டது."],
    [/No cancelled bookings\./gi, "ரத்து செய்யப்பட்ட முன்பதிவுகள் இல்லை."],
    [/Could not mark picked up\./gi, "பெற்றுக்கொண்டதாக குறிக்க முடியவில்லை."],
    [/Updating\.\.\./gi, "புதுப்பிக்கிறது..."],
    [/\bCurrent Laundry\b/gi, "தற்போதைய சலவை"],
    [/\bScan Tag Image\b/gi, "டேக் படத்தை ஸ்கேன் செய்க"],
    [/Bag Tag Image/gi, "பை டேக் படம்"],
    [/Extract and Save Token/gi, "டோக்கனை எடுத்துப் சேமிக்கவும்"],
    [/Upload a tag image to extract and save the token\./gi, "டோக்கனை எடுத்து சேமிக்க டேக் படத்தை பதிவேற்றவும்."],
    [/Only the numeric portion of the tag is stored as the token number\./gi, "டேக்கில் உள்ள எண் பகுதி மட்டும் டோக்கன் எண்ணாக சேமிக்கப்படும்."],
    [/Token can be generated only on the scheduled booking date\./gi, "முன்பதிவு செய்யப்பட்ட நாளில்தான் டோக்கனை உருவாக்க முடியும்."],
    [/No active batches/gi, "செயலில் உள்ள தொகுப்புகள் இல்லை"],
    [/No students scheduled for today/gi, "இன்றைக்கு மாணவர் முன்பதிவுகள் இல்லை"],
    [/No bookings scheduled/gi, "முன்பதிவுகள் இல்லை"],
    [/No bookings found/gi, "முன்பதிவுகள் கிடைக்கவில்லை"],
    [/Recent Active Batches/gi, "சமீபத்திய செயலில் உள்ள தொகுப்புகள்"],
    [/Today's Schedule/gi, "இன்றைய அட்டவணை"],
    [/Today's Appointment Board/gi, "இன்றைய முன்பதிவு பலகை"],
    [/View All Bookings/gi, "அனைத்து முன்பதிவுகளையும் காண்க"],
    [/No students have booked a slot for today yet\./gi, "இன்றைக்கு எந்த மாணவரும் நேரத்தை முன்பதிவு செய்யவில்லை."],
    [/\bStudent\b/gi, "மாணவர்"],
    [/\bSlot\b/gi, "நேரம்"],
    [/\bStatus\b/gi, "நிலை"],
    [/\bReg No\b/gi, "பதிவு எண்"],
    [/\bDate\b/gi, "தேதி"],
    [/\bRoom\b/gi, "அறை"],
    [/\bFloor\b/gi, "தளம்"],
    [/\bHome\b/gi, "முகப்பு"],
    [/\bLoading\.\.\.\b/gi, "ஏற்றுகிறது..."],
    [/\bNo notifications yet\.\b/gi, "இதுவரை அறிவிப்புகள் இல்லை."],
    [/You have a new announcement\./gi, "உங்களுக்கு புதிய அறிவிப்பு உள்ளது."],
    [/You have new laundry notifications\./gi, "உங்களுக்கு புதிய சலவை அறிவிப்புகள் உள்ளன."],
    [/Create Urgent Request/gi, "அவசர கோரிக்கை உருவாக்கு"],
    [/Send Request/gi, "கோரிக்கையை அனுப்பு"],
    [/No bucket requests yet\./gi, "இன்னும் பக்கெட் கோரிக்கைகள் இல்லை."],
    [/Sunday/gi, "ஞாயிறு"],
    [/Monday/gi, "திங்கள்"],
    [/Tuesday/gi, "செவ்வாய்"],
    [/Wednesday/gi, "புதன்"],
    [/Thursday/gi, "வியாழன்"],
    [/Friday/gi, "வெள்ளி"],
    [/Saturday/gi, "சனி"]
  ];

  function setLanguage(lang) {
    if (!SUPPORTED[lang]) return;
    currentLanguage = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    applyLanguage();
    syncToggles();
    window.dispatchEvent(new CustomEvent("portal-language-changed", { detail: { lang: currentLanguage } }));
  }

  function translateText(text) {
    let out = text;
    for (const [pattern, replacement] of REPLACEMENTS) out = out.replace(pattern, replacement);
    return out;
  }

  function processTextNode(node) {
    if (!node || !node.nodeValue) return;
    const raw = node.nodeValue;
    if (!raw.trim()) return;
    if (!originalTextMap.has(node)) originalTextMap.set(node, raw);
    const original = originalTextMap.get(node) || raw;
    const nextValue = currentLanguage === "ta" ? translateText(original) : original;
    if (node.nodeValue !== nextValue) node.nodeValue = nextValue;
  }

  function processElementAttributes(el) {
    if (!el || el.nodeType !== 1) return;
    ["placeholder", "title", "aria-label"].forEach((attr) => {
      if (!el.hasAttribute(attr)) return;
      const key = `data-i18n-original-${attr}`;
      if (!el.hasAttribute(key)) el.setAttribute(key, el.getAttribute(attr));
      const original = el.getAttribute(key) || "";
      const nextValue = currentLanguage === "ta" ? translateText(original) : original;
      if (el.getAttribute(attr) !== nextValue) el.setAttribute(attr, nextValue);
    });
  }

  function walkAndProcess(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      processTextNode(root);
      return;
    }
    if (root.nodeType !== 1) return;
    const tag = root.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return;

    processElementAttributes(root);

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
      const parentTag = node.parentElement ? node.parentElement.tagName : "";
      if (parentTag === "SCRIPT" || parentTag === "STYLE" || parentTag === "NOSCRIPT") continue;
      processTextNode(node);
    }

    root.querySelectorAll("*").forEach(processElementAttributes);
  }

  function syncToggles() {
    document.querySelectorAll(".portal-lang-toggle").forEach((el) => {
      el.value = currentLanguage;
    });
  }

  function applyLanguage() {
    if (isApplying) return;
    isApplying = true;
    try {
      document.documentElement.lang = currentLanguage === "ta" ? "ta" : "en";
      walkAndProcess(document.body);
    } finally {
      isApplying = false;
    }
  }

  function initToggleHandlers() {
    document.querySelectorAll(".portal-lang-toggle").forEach((el) => {
      el.addEventListener("change", (e) => setLanguage(e.target.value));
    });
  }

  function startObserver() {
    const observer = new MutationObserver((mutations) => {
      if (isApplying || currentLanguage !== "ta") return;
      isApplying = true;
      try {
        for (const m of mutations) m.addedNodes.forEach((n) => walkAndProcess(n));
      } finally {
        isApplying = false;
      }
    });
    observer.observe(document.body, observerConfig);
  }

  function init() {
    if (!document.body) return;
    initToggleHandlers();
    syncToggles();
    applyLanguage();
    startObserver();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.portalI18n = { setLanguage, getLanguage: () => currentLanguage };
})();
