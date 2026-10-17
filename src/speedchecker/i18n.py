"""Bilingual UI strings (English / فارسی). ``tr(lang, key)`` everywhere."""

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "SpeedChecker — Internet & VPN Speed Test",
        "home": "Home",
        "servers": "VPN Locations",
        "history": "History",
        "logs": "Live Log",
        "settings": "Settings",
        "download": "Download",
        "upload": "Upload",
        "latency": "Latency",
        "ping": "Ping (ms)",
        "jitter_server": "Server",
        "start_test": "▶  Start Test",
        "stop": "■  Stop",
        "test_selected": "Test Selected",
        "batch_test": "Batch Test (selection / list order)",
        "fetch_servers": "↻  Fetch ExpressVPN Locations",
        "search": "Search server / city / country / sponsor…",
        "group_by": "Group by",
        "sort_by": "Order by",
        "none": "None",
        "country": "Country",
        "sponsor": "Sponsor",
        "letter": "First letter",
        "name": "Name",
        "city": "City",
        "host": "VPN region ID",
        "distance": "Distance",
        "random": "Random",
        "file_order": "File / list order",
        "load_file": "Load list from JSON file…",
        "demo_mode": "Demo mode (offline simulation)",
        "language": "Language / زبان",
        "unit": "Speed unit (b = bits, B = bytes; /s = per second)",
        "baseline": "Measure direct connection once before VPN tests",
        "download_ookla": "Ookla CLI",
        "download_button": "⬇  Download official CLI into vendor/",
        "redownload_ookla": "⬇  Re-download official CLI into vendor/",
        "download_status": "Status",
        "ookla_missing": "not installed — the built-in engine will be used",
        "ookla_ready": "ready — {path} ({size})",
        "download_start": "Downloading the official Ookla CLI…",
        "download_progress": "Downloading… {percent}% ({done} / {total})",
        "download_progress_unknown": "Downloading… {done}",
        "download_done_title": "Ookla CLI downloaded",
        "download_done": "The official Ookla Speedtest CLI was saved to:\n{path}\n\n"
        "Size: {size}. Auto keeps the live built-in engine first and uses Ookla "
        "only if needed. Select Ookla manually for final-only results. Nothing "
        "was installed system-wide.",
        "download_failed_title": "Ookla download failed",
        "download_failed_status": "Download failed — see the log.",
        "ookla_page": "Ookla website",
        "ookla_page_button": "↗  Official download page",
        "tip_backend": "Which engine measures speed. Auto uses the built-in engine "
        "first so gauges update live, then falls back to an installed Ookla binary if "
        "needed. The Ookla CLI reports final results only; its option tries Ookla "
        "first and falls back "
        "to the built-in engine on failure.",
        "tip_repeat": "How many times each measurement is repeated; the result is "
        "the average. Repetitions run one after another.",
        "tip_timeout_conn": "How long to wait for ExpressVPN to report a connected "
        "or disconnected state.",
        "tip_timeout_cmd": "Maximum run time for a single expressvpnctl command.",
        "tip_timeout_test": "Maximum run time for one speed test (Ookla binary or "
        "built-in engine).",
        "tip_duration": "Length of each download and upload phase for the built-in "
        "engine, in seconds.",
        "tip_connections": "How many simultaneous connections the built-in engine "
        "opens during each download/upload phase. 4–8 usually saturates a fast link; "
        "the Ookla binary manages its own connections and ignores this value.",
        "tip_accept_license": "Ookla requires this before its CLI can be downloaded "
        "or run.",
        "tip_vpn_mode": "Connect to each selected ExpressVPN location before "
        "measuring it.",
        "tip_disconnect_existing": "Allow SpeedChecker to disconnect an existing VPN. "
        "The previous connection is not restored afterwards.",
        "tip_baseline": "Measure the direct connection once before the VPN tests, "
        "for comparison.",
        "accept_first": "Accept the Ookla license/GDPR in Settings before downloading.",
        "size_unit": "Size unit",
        "repeat": "Repetitions per test",
        "timeout_conn": "Connection timeout (s)",
        "timeout_cmd": "Command timeout (s)",
        "timeout_test": "Speed-test timeout (s)",
        "duration": "Duration per phase (s)",
        "connections": "Parallel connections (built-in engine)",
        "backend": "Speed engine",
        "backend_auto": "Auto (live built-in → Ookla fallback if available)",
        "backend_builtin": "Built-in (live, bundled pure Python)",
        "backend_ookla": "Ookla first (final-only; built-in fallback)",
        "backend_demo": "Demo (simulated)",
        "accept_license": "Accept Ookla license/GDPR",
        "vpn_mode": "Connect to selected ExpressVPN location",
        "disconnect_existing": "Disconnect existing VPN first",
        "status": "Status",
        "connection": "Connection",
        "all": "All",
        "ok_only": "Successful only",
        "errors_only": "Errors only",
        "min_download": "Min download (Mbps)",
        "max_latency": "Max ping (ms)",
        "filter_text": "Filter text…",
        "clear_history": "Clear history",
        "export": "Export…",
        "clear_log": "Clear log",
        "save_log": "Save log…",
        "ready": "Ready",
        "testing": "Testing…",
        "live": "Live speed",
        "results": "Result",
        "time": "Time",
        "location": "Location",
        "error": "Error",
        "mode": "Mode",
        "apply": "Apply & Save",
        "history_file": "History file",
        "avg_of": "average of {n}",
        "batch_order": "Batch order",
        "group_servers_hint": "ExpressVPN locations from expressvpnctl. Selecting a group selects every endpoint in it; Ctrl-click adds endpoints. Tests run in the order you select them. Speed is measured via a separate Ookla server.",  # noqa: E501
    },
    "fa": {
        "app_title": "اسپیدچکر — تست سرعت اینترنت و VPN",
        "home": "خانه",
        "servers": "لوکیشن‌های VPN",
        "history": "تاریخچه",
        "logs": "لاگ زنده",
        "settings": "تنظیمات",
        "download": "دانلود",
        "upload": "آپلود",
        "latency": "تأخیر",
        "ping": "پینگ (ms)",
        "jitter_server": "سرور",
        "start_test": "▶  شروع تست",
        "stop": "■  توقف",
        "test_selected": "تست سرور انتخاب‌شده",
        "batch_test": "تست دسته‌ای (به ترتیب انتخاب/لیست)",
        "fetch_servers": "↻  دریافت همهٔ لوکیشن‌های ExpressVPN",
        "search": "جستجوی سرور / شهر / کشور / اسپانسر…",
        "group_by": "دسته‌بندی",
        "sort_by": "ترتیب",
        "none": "بدون دسته‌بندی",
        "country": "کشور",
        "sponsor": "اسپانسر",
        "letter": "حرف اول",
        "name": "نام",
        "city": "شهر",
        "host": "شناسهٔ لوکیشن VPN",
        "distance": "فاصله",
        "random": "تصادفی",
        "file_order": "ترتیب فایل/لیست",
        "load_file": "بارگذاری لیست از فایل JSON…",
        "demo_mode": "حالت دمو (شبیه‌سازی آفلاین)",
        "language": "Language / زبان",
        "unit": "واحد سرعت (b = بیت، B = بایت؛ /s = در ثانیه)",
        "baseline": "یک‌بار تست بدون VPN پیش از تست‌ها",
        "download_ookla": "باینری Ookla",
        "download_button": "⬇  دریافت باینری رسمی در vendor/",
        "redownload_ookla": "⬇  دریافت دوبارهٔ باینری در vendor/",
        "download_status": "وضعیت",
        "ookla_missing": "نصب نیست — از موتور داخلی استفاده می‌شود",
        "ookla_ready": "آماده — {path} ({size})",
        "download_start": "در حال دانلود باینری رسمی Ookla…",
        "download_progress": "در حال دانلود… {percent}٪ ({done} / {total})",
        "download_progress_unknown": "در حال دانلود… {done}",
        "download_done_title": "باینری Ookla دانلود شد",
        "download_done": "باینری رسمی Ookla در این مسیر ذخیره شد:\n{path}\n\n"
        "حجم: {size}. حالت خودکار ابتدا از موتور داخلی زنده استفاده می‌کند و در "
        "صورت نیاز به Ookla برمی‌گردد. برای نتیجهٔ نهایی Ookla را دستی انتخاب کنید. "
        "نصب سیستمی انجام نشد.",
        "download_failed_title": "دانلود Ookla ناموفق بود",
        "download_failed_status": "دانلود ناموفق — جزئیات در لاگ",
        "ookla_page": "سایت Ookla",
        "ookla_page_button": "↗  صفحهٔ رسمی دانلود",
        "tip_backend": "موتوری که سرعت را می‌سنجد. حالت خودکار ابتدا از موتور داخلی "
        "استفاده می‌کند تا کیلومترشمار زنده باشد و در صورت نیاز به Ookla برمی‌گردد. "
        "CLI اوکلا فقط نتیجهٔ نهایی را می‌دهد؛ گزینهٔ Ookla ابتدا آن را امتحان می‌کند "
        "و در صورت خطا به موتور داخلی برمی‌گردد.",
        "tip_repeat": "تعداد تکرار هر اندازه‌گیری؛ نتیجه میانگین آن‌هاست. تکرارها "
        "پشت سر هم اجرا می‌شوند.",
        "tip_timeout_conn": "مدت انتظار برای گزارش وضعیت متصل/قطع‌شده از "
        "ExpressVPN.",
        "tip_timeout_cmd": "حداکثر زمان اجرای یک دستور expressvpnctl.",
        "tip_timeout_test": "حداکثر زمان یک تست سرعت (باینری Ookla یا موتور "
        "داخلی).",
        "tip_duration": "مدت هر فاز دانلود و آپلود در موتور داخلی، به ثانیه.",
        "tip_connections": "تعداد اتصال‌های هم‌زمانی که موتور داخلی در هر فاز "
        "دانلود/آپلود باز می‌کند. مقدار ۴ تا ۸ معمولاً برای اینترنت پرسرعت کافی "
        "است؛ باینری Ookla اتصال‌های خودش را مدیریت می‌کند و این مقدار را نادیده "
        "می‌گیرد.",
        "tip_accept_license": "اوکلا پیش از دانلود یا اجرای CLI خود این را الزامی "
        "می‌داند.",
        "tip_vpn_mode": "پیش از هر اندازه‌گیری به لوکیشن انتخاب‌شدهٔ ExpressVPN "
        "وصل شو.",
        "tip_disconnect_existing": "اجازه می‌دهد اسپیدچکر VPN موجود را قطع کند. "
        "اتصال قبلی بعد از تست بازگردانده نمی‌شود.",
        "tip_baseline": "یک‌بار اتصال مستقیم را پیش از تست‌های VPN برای مقایسه "
        "اندازه بگیر.",
        "accept_first": "ابتدا پذیرش لایسنس/GDPR اوکلا را در تنظیمات فعال کنید.",
        "size_unit": "واحد حجم",
        "repeat": "تعداد تکرار هر تست",
        "timeout_conn": "تایم‌اوت اتصال (ثانیه)",
        "timeout_cmd": "تایم‌اوت دستور (ثانیه)",
        "timeout_test": "تایم‌اوت هر تست سرعت (ثانیه)",
        "duration": "مدت هر فاز (ثانیه)",
        "connections": "اتصال‌های موازی (موتور داخلی)",
        "backend": "موتور تست سرعت",
        "backend_auto": "خودکار (موتور داخلی زنده ← Ookla در صورت نصب و خطا)",
        "backend_builtin": "داخلی (زنده، پایتون خالص همراه پروژه)",
        "backend_ookla": "ابتدا Ookla (فقط نتیجهٔ نهایی؛ موتور داخلی جایگزین)",
        "backend_demo": "دمو (شبیه‌سازی)",
        "accept_license": "پذیرش لایسنس/GDPR اوکلا",
        "vpn_mode": "اتصال به لوکیشن انتخابی ExpressVPN",
        "disconnect_existing": "قطع اتصال VPN فعلی",
        "status": "وضعیت",
        "connection": "اتصال",
        "all": "همه",
        "ok_only": "فقط موفق‌ها",
        "errors_only": "فقط خطاها",
        "min_download": "حداقل دانلود (Mbps)",
        "max_latency": "حداکثر پینگ (ms)",
        "filter_text": "متن فیلتر…",
        "clear_history": "پاک‌کردن تاریخچه",
        "export": "خروجی…",
        "clear_log": "پاک‌کردن لاگ",
        "save_log": "ذخیره لاگ…",
        "ready": "آماده",
        "testing": "در حال تست…",
        "live": "سرعت لحظه‌ای",
        "results": "نتیجه",
        "time": "زمان",
        "location": "لوکیشن",
        "error": "خطا",
        "mode": "حالت",
        "apply": "اعمال و ذخیره",
        "history_file": "فایل تاریخچه",
        "avg_of": "میانگین {n} تست",
        "batch_order": "ترتیب تست دسته‌ای",
        "group_servers_hint": "لوکیشن‌های ExpressVPN از expressvpnctl دریافت می‌شوند. با انتخاب یک گروه، همهٔ اندپوینت‌های آن هم انتخاب می‌شوند؛ با Ctrl می‌توانید به انتخاب اضافه کنید. تست‌ها به همان ترتیب انتخاب اجرا می‌شوند. سنجش سرعت روی سرور جداگانهٔ Ookla انجام می‌شود.",  # noqa: E501
    },
}

LANGUAGES = ("en", "fa")


def tr(lang: str, key: str) -> str:
    return STRINGS.get(lang, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))


def is_rtl(lang: str) -> bool:
    return lang == "fa"
