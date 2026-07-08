# ============================================================
#  AstroVed AI Chatbot — Complete TOPIC_MAP
#  Covers every category & subcategory from astroved.com
#  Drop this file into your backend and import it in main.py:
#      from topic_map import TOPIC_MAP, match_topic
# ============================================================

SITE = "https://www.astroved.com"

TOPIC_MAP = {

    # ─────────────────────────────────────────────
    # 1. PREDICTION SERVICES — top-level
    # ─────────────────────────────────────────────
    "prediction_services": {
        "keywords": [
            "prediction", "predictions", "future", "forecast", "reading",
            "prediction service", "astrology service", "consult", "consultation"
        ],
        "url": f"{SITE}/prediction-services-c17.aspx",
        "label": "🔮 Prediction Services",
    },

    # ── 1a. Astrology ──
    "astrology": {
        "keywords": [
            "astrology", "astrologer", "horoscope", "birth chart", "kundli",
            "kundali", "natal chart", "janam kundali", "jyotish", "vedic astrology",
            "planet", "planetary", "zodiac", "rashi", "moon sign", "sun sign",
            "ascendant", "lagna", "dasha", "mahadasha", "antardasha",
            "transit", "retrograde", "aspect", "conjunction"
        ],
        "url": f"{SITE}/astrology-c20.aspx",
        "label": "🌟 Astrology Services",
    },

    "free_reports": {
        "keywords": [
            "free report", "free chart", "free horoscope", "automated report",
            "free birth chart report", "free automated",
            "free reading", "free birth chart", "free kundli", "free tool",
            "free astrology", "complimentary", "no cost report"
        ],
        "url": f"{SITE}/free-automated-reports-c19.aspx",
        "label": "📊 Free & Automated Reports",
    },

    "ask_astrologer": {
        "keywords": [
            "ask astrologer", "ask a question", "3 questions", "three questions",
            "astrologer question", "question to astrologer", "query astrologer",
            "astrology question", "ask expert"
        ],
        "url": f"{SITE}/ask-astrologer-3-questions-c43.aspx",
        "label": "❓ Ask Astrologer 3 Questions",
    },

    "customized_reports": {
        "keywords": [
            "customized report", "personalised report", "custom report",
            "detailed report", "personal report", "in-depth report",
            "full report", "comprehensive report", "paid report"
        ],
        "url": f"{SITE}/customized-reports-c18.aspx",
        "label": "📋 Customized Reports",
    },

    "live_consultation": {
        "keywords": [
            "live consultation", "live astrology", "talk to astrologer",
            "speak to astrologer", "consult astrologer", "one on one",
            "personal consultation", "call astrologer", "chat astrologer",
            "live session", "book consultation", "schedule consultation",
            "appointment", "astrologer appointment"
        ],
        "url": f"{SITE}/live-astrology-consultation-c34.aspx",
        "label": "📞 Live Astrology Consultation",
    },

    "prasna": {
        "keywords": [
            "prasna", "prashna", "horary", "horary astrology", "instant insight",
            "quick answer", "immediate answer", "yes no question",
            "burning question", "urgent question", "prasna reading"
        ],
        "url": f"{SITE}/instant-insight-prasna--c35.aspx",
        "label": "⚡ Instant Insight (Prasna)",
    },

    "electional_astrology": {
        "keywords": [
            "electional", "muhurta", "muhurat", "auspicious time", "best time",
            "good time", "lucky time", "auspicious date", "wedding date",
            "marriage date", "business launch", "housewarming date",
            "travel date", "start date"
        ],
        "url": f"{SITE}/electional-astrology-c237.aspx",
        "label": "📅 Electional Astrology (Muhurta)",
    },

    # ── 1b. Nadi Astrology ──
    "nadi_astrology": {
        "keywords": [
            "nadi", "nadi astrology", "nadi reading", "palm leaf reading",
            "palm leaf", "nadi shastra", "agastya nadi", "nadi chapter",
            "nadi palm", "ancient reading", "thumb impression",
            "past life reading", "nadi jyotish"
        ],
        "url": f"{SITE}/nadi-astrology-c15.aspx",
        "label": "📜 Nadi Astrology",
    },

    "nadi_chapters": {
        "keywords": [
            "nadi chapter", "chapter 1", "chapter 13", "chapter 14",
            "nadi package", "nadi essential", "nadi bundle",
            "nadi chapters", "nadi combination"
        ],
        "url": f"{SITE}/nadi-chapters-c36.aspx",
        "label": "📖 Nadi Chapters",
    },

    # ── 1c. Oracle & Channel Readings ──
    "live_oracle": {
        "keywords": [
            "oracle", "oracle reading", "live oracle", "angel reading",
            "vishnu maya", "divine reading", "intuitive reading",
            "psychic reading", "channel reading", "channelling"
        ],
        "url": f"{SITE}/live-oracle-readings-c39.aspx",
        "label": "🌠 Live Oracle Readings",
    },

    "vishnu_maya": {
        "keywords": [
            "vishnu maya", "angel reading", "vishnu maya angel",
            "angel message", "divine message"
        ],
        "url": f"{SITE}/vishnu-maya-angel-reading-c40.aspx",
        "label": "👼 Vishnu Maya Angel Reading",
    },

    "agastya_reading": {
        "keywords": [
            "agastya", "agastya reading", "agastya channel", "agastya live",
            "siddha reading", "siddha channel", "agasthya"
        ],
        "url": f"{SITE}/agastya-live-channel-reading-c369.aspx",
        "label": "🔭 Agastya Live Channel Reading",
    },

    # ─────────────────────────────────────────────
    # 2. REMEDY SERVICES — top-level
    # ─────────────────────────────────────────────
    "remedy_services": {
        "keywords": [
            "remedy", "remedies", "remedy service", "vedic remedy",
            "karmic remedy", "planetary remedy", "dosha remedy",
            "pariharam", "dosha pariharam", "remedy for problem",
            "fix problem", "solution", "vedic solution"
        ],
        "url": f"{SITE}/remedy-services-c4.aspx",
        "label": "🌿 Remedy Services",
    },

    # ── 2a. Fire Lab / Homa ──
    "fire_lab": {
        "keywords": [
            "fire lab", "homa", "homam", "yagna", "yajna", "havana", "havan",
            "fire ritual", "fire prayer", "agni", "fire ceremony",
            "fire puja", "sacred fire", "fire offering"
        ],
        "url": f"{SITE}/fire-lab-homa--c8.aspx",
        "label": "🔥 Fire Lab (Homa)",
    },

    "planetary_fire_lab": {
        "keywords": [
            "planetary fire lab", "planet homa", "planet homam",
            "saturn fire lab", "sun fire lab", "moon fire lab", "mars fire lab",
            "mercury fire lab", "jupiter fire lab", "venus fire lab",
            "rahu fire lab", "ketu fire lab", "navagraha fire lab",
            "sun homa", "moon homa", "mars homa", "mercury homa",
            "jupiter homa", "venus homa", "saturn homa", "rahu homa",
            "ketu homa", "surya homa", "chandra homa", "mangal homa",
            "budha homa", "guru homa", "shukra homa", "shani homa",
            "navagraha homa", "navagraha fire lab", "9 planet homa"
        ],
        "url": f"{SITE}/planetary-fire-lab-c7.aspx",
        "label": "🪐 Planetary Fire Lab",
    },

    "deity_fire_lab": {
        "keywords": [
            "deity fire lab", "god fire lab", "goddess fire lab",
            "ganesha fire lab", "lakshmi fire lab", "shiva fire lab",
            "vishnu fire lab", "durga fire lab", "murugan fire lab",
            "archetype fire lab", "ganesha homa", "lakshmi homa",
            "shiva homa", "vishnu homa", "durga homa", "murugan homa",
            "saraswati homa", "hanuman homa", "subrahmanya homa",
            "narasimha homa", "devi homa"
        ],
        "url": f"{SITE}/archetype-deity-fire-lab-c9.aspx",
        "label": "🕉️ Archetype (Deity) Fire Lab",
    },

    "purpose_fire_lab": {
        "keywords": [
            "specific purpose fire lab", "purpose homa", "wealth homa",
            "health homa", "marriage homa", "job homa", "business homa",
            "protection homa", "prosperity homa", "success homa",
            "fertility homa", "child homa", "education homa"
        ],
        "url": f"{SITE}/specific-purpose-fire-lab-c10.aspx",
        "label": "🎯 Specific Purpose Fire Lab",
    },

    # ── 2b. Pooja ──
    "pooja": {
        "keywords": [
            "pooja", "puja", "poojai", "archana", "worship", "ritual",
            "prayer service", "vedic pooja", "temple pooja", "pooja service"
        ],
        "url": f"{SITE}/pooja-c11.aspx",
        "label": "🪔 Pooja Services",
    },

    "planetary_pooja": {
        "keywords": [
            "planetary pooja", "planet pooja", "sun pooja", "moon pooja",
            "mars pooja", "mercury pooja", "jupiter pooja", "venus pooja",
            "saturn pooja", "rahu pooja", "ketu pooja",
            "surya pooja", "chandra pooja", "mangala pooja",
            "budha pooja", "guru pooja", "shukra pooja", "shani pooja",
            "navagraha pooja", "9 planet pooja"
        ],
        "url": f"{SITE}/planetary-pooja-c12.aspx",
        "label": "🪐 Planetary Pooja",
    },

    "deity_pooja": {
        "keywords": [
            "deity pooja", "god pooja", "goddess pooja", "archetype pooja",
            "ganesha pooja", "lakshmi pooja", "shiva pooja", "vishnu pooja",
            "durga pooja", "murugan pooja", "saraswati pooja",
            "hanuman pooja", "krishna pooja", "rama pooja",
            "narasimha pooja", "devi pooja", "kartikeya pooja"
        ],
        "url": f"{SITE}/archetype-deity-pooja-c13.aspx",
        "label": "🕉️ Archetype (Deity) Pooja",
    },

    "purpose_pooja": {
        "keywords": [
            "specific purpose pooja", "purpose pooja", "wealth pooja",
            "health pooja", "marriage pooja", "job pooja", "business pooja",
            "protection pooja", "prosperity pooja", "success pooja",
            "fertility pooja", "child pooja", "education pooja",
            "house pooja", "vehicle pooja", "griha pravesh"
        ],
        "url": f"{SITE}/specific-purpose-pooja-c14.aspx",
        "label": "🎯 Specific Purpose Pooja",
    },

    # ── 2c. Ancestral Remedies ──
    "ancestral_remedies": {
        "keywords": [
            "ancestral", "ancestor", "pitru", "pitru dosha", "pitra dosha",
            "ancestral remedy", "tarpanam",
            "new moon ritual", "ancestral karma", "forefathers",
            "dead ancestors", "ancestral blessing", "pitru pooja"
        ],
        "url": f"{SITE}/ancestral-remedies-c48.aspx",
        "label": "🙏 Ancestral Remedies",
    },

    "tarpanam": {
        "keywords": [
            "tarpanam", "tarpan", "tharpanam", "tarpanam ritual", "new moon tarpanam",
            "monthly tarpanam", "annual tarpanam", "maha tarpanam",
            "pitru tarpan", "ancestor water offering"
        ],
        "url": f"{SITE}/tarpanam-c49.aspx",
        "label": "💧 Tarpanam",
    },

    "kerala_remedy": {
        "keywords": [
            "kerala remedy", "kerala ritual", "kerala homa",
            "kerala pooja", "kerala archana", "kerala abishekam",
            "kerala nivedhyam", "lamp lighting kerala",
            "kerala temple", "south india remedy"
        ],
        "url": f"{SITE}/kerala-remedy-c50.aspx",
        "label": "🌴 Kerala Remedy",
    },

    # ── 2d. Other Remedy Services ──
    "written_mantra": {
        "keywords": [
            "written mantra", "mantra writing", "mantra service",
            "likhit japa", "written japa", "yantra mantra",
            "mantra scroll", "mantra script"
        ],
        "url": f"{SITE}/written-mantra-c51.aspx",
        "label": "✍️ Written Mantra",
    },

    "karuppusamy": {
        "keywords": [
            "karuppusamy", "karuppuswamy", "karuppasamy", "karuppar",
            "karuppusamy remedy", "karuppusamy pooja",
            "village deity", "folk deity"
        ],
        "url": f"{SITE}/karuppusamy-remedies-c42.aspx",
        "label": "🗡️ Karuppusamy Remedies",
    },

    "pradosham": {
        "keywords": [
            "pradosham", "pradosh", "pradosham pooja", "pradosham ritual",
            "shiva pradosham", "pradosha vrat", "trayodashi",
            "bi-monthly shiva", "shiva worship pradosha"
        ],
        "url": f"{SITE}/pradosham-c124.aspx",
        "label": "🌙 Pradosham",
    },

    "kerala_remedies_all": {
        "keywords": [
            "kerala remedies", "kerala services", "kerala temple ritual",
            "kerala homa fire", "kerala archana pooja", "kerala abishekam ritual",
            "kerala nivedhyam offering", "lamp lighting service"
        ],
        "url": f"{SITE}/kerala-remedies-c338.aspx",
        "label": "🌴 Kerala Remedies",
    },

    "trip": {
        "keywords": [
            "trip", "temple trip", "pilgrimage", "spiritual trip",
            "temple tour", "kashi trip", "tirupati trip",
            "india pilgrimage", "temple visit", "group trip"
        ],
        "url": f"{SITE}/trip-c414.aspx",
        "label": "✈️ Spiritual Trip",
    },

    # ─────────────────────────────────────────────
    # 3. PRODUCTS — top-level
    # ─────────────────────────────────────────────
    "products": {
        "keywords": [
            "product", "products", "buy", "shop", "store", "purchase",
            "order", "physical product", "spiritual product",
            "vedic product", "sacred item", "energized product"
        ],
        "url": f"{SITE}/products-c1.aspx",
        "label": "🛍️ All Products",
    },

    # ── 3a. Yantra ──
    "yantra": {
        "keywords": [
            "yantra", "yantras", "sri yantra", "shri yantra",
            "sacred geometry", "energized yantra", "copper yantra",
            "silver yantra", "gold yantra", "yantra plate",
            "yantra pendant", "planet yantra", "god yantra"
        ],
        "url": f"{SITE}/yantra-c2.aspx",
        "label": "🔱 Yantras",
    },

    "yantra_gods": {
        "keywords": [
            "ganesha yantra", "lakshmi yantra", "shiva yantra",
            "vishnu yantra", "saraswati yantra", "hanuman yantra",
            "murugan yantra", "durga yantra", "krishna yantra",
            "rama yantra", "god yantra", "deity yantra"
        ],
        "url": f"{SITE}/gods-c402.aspx",
        "label": "🕉️ God Yantras",
    },

    "yantra_goddess": {
        "keywords": [
            "goddess yantra", "devi yantra", "kali yantra",
            "tripura sundari yantra", "kamala yantra",
            "feminine yantra", "shakti yantra"
        ],
        "url": f"{SITE}/goddess-c403.aspx",
        "label": "🌸 Goddess Yantras",
    },

    "yantra_planets": {
        "keywords": [
            "planetary yantra", "planet yantra", "sun yantra", "moon yantra",
            "mars yantra", "mercury yantra", "jupiter yantra",
            "venus yantra", "saturn yantra", "rahu yantra", "ketu yantra",
            "surya yantra", "navagraha yantra"
        ],
        "url": f"{SITE}/planets-c404.aspx",
        "label": "🪐 Planetary Yantras",
    },

    # ── 3b. Crystal and Beads ──
    "crystal_beads": {
        "keywords": [
            "crystal", "crystals", "crystal bead", "crystal beads",
            "shiva lingam", "crystal lingam", "healing crystal",
            "gemstone bead", "energized crystal", "sacred crystal",
            "crystal healing", "crystal ball"
        ],
        "url": f"{SITE}/crystal-and-beads-c21.aspx",
        "label": "💎 Crystal and Beads",
    },

    # ── 3c. Malas ──
    "mala": {
        "keywords": [
            "mala", "malas", "mala bead", "mala beads", "108 beads",
            "prayer bead", "meditation bead", "rudraksha mala",
            "tulsi mala", "hematite mala", "turquoise mala",
            "jade mala", "amethyst mala", "citrine mala",
            "chakra mala", "rainbow mala", "shiva shakti mala",
            "tiger eye mala", "aquamarine mala", "spiritual mala",
            "shreem brzee mala", "agate mala", "radiation mala",
            "african blue jade mala", "jupiter mala", "bermuda jade mala",
            "mala necklace", "japa mala", "japa beads",
            "mala for meditation", "meditation necklace"
        ],
        "url": f"{SITE}/malas-c22.aspx",
        "label": "📿 Browse All Malas",
    },

    "special_malas": {
        "keywords": [
            "special mala", "premium mala", "exclusive mala",
            "shiva shakti mala", "shreem brzee", "spiritual mala 108",
            "energized spiritual mala", "7 chakra mala", "chakra cleansing mala"
        ],
        "url": f"{SITE}/special-malas-c286.aspx",
        "label": "⭐ Special Malas",
    },

    "mala_gods": {
        "keywords": [
            "god mala", "narasimha mala", "tiger eye narasimha",
            "deity mala", "god bead", "narasimha pendant mala"
        ],
        "url": f"{SITE}/gods-c394.aspx",
        "label": "🕉️ God Malas",
    },

    "mala_goddess": {
        "keywords": [
            "goddess mala", "feminine mala", "shakti mala",
            "shreem brzee feminine", "devi mala", "lakshmi mala bead"
        ],
        "url": f"{SITE}/goddess-c390.aspx",
        "label": "🌸 Goddess Malas",
    },

    "mala_planets": {
        "keywords": [
            "planetary mala", "planet mala", "saturn mala", "jupiter mala",
            "hematite saturn mala", "citrine jupiter mala",
            "sun mala", "moon mala", "mars mala", "rahu mala"
        ],
        "url": f"{SITE}/planets-c395.aspx",
        "label": "🪐 Planetary Malas",
    },

    # ── 3d. Herbal Remedy Incense ──
    "incense": {
        "keywords": [
            "incense", "incense stick", "agarbatti", "dhoop", "herbal incense",
            "remedy incense", "planet incense", "planet earth incense",
            "aromatherapy", "sacred smoke", "incense remedy", "herbal dhoop"
        ],
        "url": f"{SITE}/herbal-remedy-incense-c25.aspx",
        "label": "🌿 Herbal Remedy Incense",
    },

    "planet_incense": {
        "keywords": [
            "planet earth incense", "planetary incense", "planet incense stick",
            "sun incense", "moon incense", "saturn incense",
            "jupiter incense", "mars incense", "venus incense",
            "rahu incense", "ketu incense"
        ],
        "url": f"{SITE}/planet-earth-incense-c28.aspx",
        "label": "🪐 Planet Earth Incense",
    },

    # ── 3e. Statue ──
    "statue": {
        "keywords": [
            "statue", "idol", "murti", "deity statue", "god statue",
            "goddess statue", "bronze statue", "brass statue",
            "copper statue", "energized statue", "figurine",
            "sacred statue", "temple idol", "home deity"
        ],
        "url": f"{SITE}/statue-c95.aspx",
        "label": "🗿 Statues / Idols",
    },

    "statue_gods": {
        "keywords": [
            "ganesha statue", "shiva statue", "vishnu statue",
            "krishna statue", "rama statue", "hanuman statue",
            "murugan statue", "narasimha statue", "god idol",
            "male deity statue", "god murti"
        ],
        "url": f"{SITE}/gods-c399.aspx",
        "label": "🕉️ God Statues",
    },

    "statue_goddess": {
        "keywords": [
            "goddess statue", "lakshmi statue", "durga statue",
            "saraswati statue", "kali statue", "devi statue",
            "parvati statue", "feminine idol", "goddess idol"
        ],
        "url": f"{SITE}/goddess-c400.aspx",
        "label": "🌸 Goddess Statues",
    },

    "statue_planets": {
        "keywords": [
            "planet statue", "navagraha statue", "planetary idol",
            "saturn statue", "jupiter statue", "sun statue", "moon statue",
            "navagraha idol", "planet murti"
        ],
        "url": f"{SITE}/planets-c401.aspx",
        "label": "🪐 Planetary Statues",
    },

    # ── 3f. Pendants ──
    "pendant": {
        "keywords": [
            "pendant", "pendants", "necklace pendant", "locket",
            "gold pendant", "silver pendant", "copper pendant",
            "deity pendant", "god pendant", "planet pendant",
            "energized pendant", "sacred pendant", "amulet pendant"
        ],
        "url": f"{SITE}/pendants-c392.aspx",
        "label": "📿 Pendants",
    },

    "pendant_gods": {
        "keywords": [
            "god pendant", "ganesha pendant", "shiva pendant",
            "vishnu pendant", "krishna pendant", "murugan pendant",
            "hanuman pendant", "narasimha pendant", "deity pendant"
        ],
        "url": f"{SITE}/gods-c396.aspx",
        "label": "🕉️ God Pendants",
    },

    "pendant_goddess": {
        "keywords": [
            "goddess pendant", "lakshmi pendant", "durga pendant",
            "saraswati pendant", "devi pendant", "kali pendant",
            "feminine pendant"
        ],
        "url": f"{SITE}/goddess-c397.aspx",
        "label": "🌸 Goddess Pendants",
    },

    "pendant_planets": {
        "keywords": [
            "planet pendant", "planetary pendant", "saturn pendant",
            "jupiter pendant", "sun pendant", "moon pendant",
            "rahu pendant", "ketu pendant", "mars pendant",
            "navagraha pendant"
        ],
        "url": f"{SITE}/planets-c398.aspx",
        "label": "🪐 Planetary Pendants",
    },

    # ── 3g. Bracelets ──
    "bracelet": {
        "keywords": [
            "bracelet", "bracelets", "wristband", "bangle", "wrist mala",
            "crystal bracelet", "gemstone bracelet", "planet bracelet",
            "energized bracelet", "healing bracelet", "protection bracelet",
            "rudraksha bracelet", "copper bracelet"
        ],
        "url": f"{SITE}/bracelets-c145.aspx",
        "label": "⚜️ Bracelets",
    },

    "bracelet_planets": {
        "keywords": [
            "planetary bracelet", "planet bracelet", "saturn bracelet",
            "jupiter bracelet", "sun bracelet", "moon bracelet",
            "mars bracelet", "navagraha bracelet"
        ],
        "url": f"{SITE}/planets-c389.aspx",
        "label": "🪐 Planetary Bracelets",
    },

    # ── 3h. Energized Copper Amulet ──
    "copper_amulet": {
        "keywords": [
            "copper amulet", "energized amulet", "amulet", "talisman",
            "copper talisman", "energized copper", "protective amulet",
            "sacred amulet", "vedic amulet"
        ],
        "url": f"{SITE}/energized-copper-amulet-c420.aspx",
        "label": "🥉 Energized Copper Amulet",
    },

    "amulet_wealth": {
        "keywords": [
            "wealth amulet", "money amulet", "prosperity amulet",
            "abundance amulet", "lakshmi amulet", "wealth boosting",
            "financial amulet", "money magnet"
        ],
        "url": f"{SITE}/wealth-boosting-c422.aspx",
        "label": "💰 Wealth Boosting Amulet",
    },

    "amulet_success": {
        "keywords": [
            "success amulet", "career amulet", "job amulet",
            "achievement amulet", "victory amulet", "success boosting",
            "promotion amulet", "business success amulet"
        ],
        "url": f"{SITE}/success-bestowing-c424.aspx",
        "label": "🏆 Success Bestowing Amulet",
    },

    "amulet_protection": {
        "keywords": [
            "protection amulet", "evil eye amulet", "negative energy amulet",
            "shield amulet", "protection boosting", "protective charm",
            "black magic protection", "evil eye protection"
        ],
        "url": f"{SITE}/protection-boosting-c423.aspx",
        "label": "🛡️ Protection Boosting Amulet",
    },

    "amulet_health": {
        "keywords": [
            "health amulet", "healing amulet", "wellness amulet",
            "recovery amulet", "health boosting", "disease healing amulet",
            "immunity amulet", "medical amulet"
        ],
        "url": f"{SITE}/health-boosting-c425.aspx",
        "label": "🩺 Health Boosting Amulet",
    },

    "amulet_planetary": {
        "keywords": [
            "planetary affliction amulet", "planet relief amulet",
            "dosha amulet", "graha dosha amulet", "planetary affliction relief",
            "saturn affliction", "rahu ketu amulet", "malefic planet amulet"
        ],
        "url": f"{SITE}/planetary-affliction-relief-c426.aspx",
        "label": "🪐 Planetary Affliction Relief Amulet",
    },

    "amulet_relationship": {
        "keywords": [
            "relationship amulet", "love amulet", "marriage amulet",
            "partner amulet", "relationship boosting", "attraction amulet",
            "romance amulet", "soulmate amulet", "couples amulet"
        ],
        "url": f"{SITE}/relationship-boosting-c421.aspx",
        "label": "❤️ Relationship Boosting Amulet",
    },

    # ─────────────────────────────────────────────
    # 4. MEMBERSHIP
    # ─────────────────────────────────────────────
    "membership": {
        "keywords": [
            "membership", "member", "subscription", "plan", "premium",
            "annual plan", "monthly plan", "join", "become member",
            "vip", "exclusive access", "member benefits", "membership plan"
        ],
        "url": f"{SITE}/membership-c321.aspx",
        "label": "👑 Membership Plans",
    },

    # ─────────────────────────────────────────────
    # 5. ON-DEMAND VIDEO
    # ─────────────────────────────────────────────
    "video": {
        "keywords": [
            "video", "videos", "on demand video", "online video",
            "astrology video", "vedic video", "video course",
            "video lecture", "recorded video", "watch video",
            "online class", "video content"
        ],
        "url": f"{SITE}/on-demand-video-c76.aspx",
        "label": "🎬 On-Demand Videos",
    },

    # ─────────────────────────────────────────────
    # 6. MOBILE APPS
    # ─────────────────────────────────────────────
    "mobile_app": {
        "keywords": [
            "mobile app", "app", "android app", "ios app", "iphone app",
            "play store", "app store", "astroved app", "download app",
            "phone app", "application", "mobile application"
        ],
        "url": f"{SITE}/mobile-apps-c172.aspx",
        "label": "📱 Mobile Apps",
    },

    # ─────────────────────────────────────────────
    # 7. FREE TOOLS (astropedia)
    # ─────────────────────────────────────────────
    "birth_chart": {
        "keywords": [
            "birth chart", "natal chart", "free birth chart", "kundli", "kundali", "janam kundali",
            "free birth chart", "free kundli", "chart calculator",
            "astrology chart", "planet positions", "lagna chart",
            "ascendant chart", "rasi chart", "navamsa"
        ],
        "url": f"{SITE}/astropedia/en/freetools/birth-chart",
        "label": "📊 Free Birth Chart",
    },

    "horoscope_matching": {
        "keywords": [
            "horoscope matching", "kundali matching", "kundli milan",
            "compatibility", "marriage compatibility", "partner match",
            "compatibility check", "gun milan", "ashtakoota",
            "marriage match", "relationship compatibility", "jodi"
        ],
        "url": f"{SITE}/astropedia/en/freetools/horoscope-matching",
        "label": "💑 Horoscope Matching",
    },

    "numerology": {
        "keywords": [
            "numerology", "numerology reading", "life path number",
            "name number", "lucky number", "numerology report",
            "birth number", "destiny number", "name numerology",
            "number astrology"
        ],
        "url": f"{SITE}/astropedia/en/freetools/numerology",
        "label": "🔢 Numerology Reading",
    },

    "gemstone_tool": {
        "keywords": [
            "gemstone", "gemstones", "gem", "gems", "lucky stone",
            "lucky gemstone", "birth stone", "birthstone",
            "ruby", "pearl", "coral", "emerald", "yellow sapphire",
            "diamond", "blue sapphire", "hessonite", "cat's eye",
            "ratna", "navaratna", "gem recommendation"
        ],
        "url": f"{SITE}/astropedia/en/freetools/gemstone",
        "label": "💎 Gemstone Recommendation",
    },

    "horoscope": {
        "keywords": [
            "horoscope", "daily horoscope", "weekly horoscope",
            "monthly horoscope", "yearly horoscope", "today horoscope",
            "rashi", "rashi bhavishya", "sun sign horoscope",
            "moon sign horoscope", "aries", "taurus", "gemini", "cancer",
            "leo", "virgo", "libra", "scorpio", "sagittarius",
            "capricorn", "aquarius", "pisces",
            "mesha", "vrishabha", "mithuna", "karka", "simha",
            "kanya", "tula", "vrischika", "dhanu", "makara", "kumbha", "meena"
        ],
        "url": f"{SITE}/horoscopes",
        "label": "🌙 Daily Horoscope",
    },

    "vastu": {
        "keywords": [
            "vastu", "vastu shastra", "vastu tips", "vastu remedy",
            "home vastu", "office vastu", "vastu for home",
            "vastu direction", "vastu consultant", "vastu dosha"
        ],
        "url": f"{SITE}/astropedia/en/vastu",
        "label": "🏠 Vastu Shastra",
    },

    "palmistry": {
        "keywords": [
            "palmistry", "palm reading", "palm report", "hand reading",
            "palm lines", "life line", "heart line", "head line",
            "fate line", "palm analysis"
        ],
        "url": f"{SITE}/palmistry-report",
        "label": "🖐️ Palm Reading Report",
    },

    # ─────────────────────────────────────────────
    # 8. LIFE AREAS (intent-based routing)
    # ─────────────────────────────────────────────
    "love_marriage": {
        "keywords": [
            "love", "romance", "relationship", "marriage", "wedding",
            "husband", "wife", "partner", "soulmate", "divorce",
            "breakup", "love problem", "marriage problem",
            "when will i marry", "love life", "spouse", "attraction"
        ],
        "url": f"{SITE}/love-marriage/love-and-relationship",
        "label": "❤️ Love & Relationships",
    },

    "career_business": {
        "keywords": [
            "career", "job", "business", "work", "profession", "employment",
            "promotion", "salary", "entrepreneur", "startup", "success",
            "career problem", "job change", "business growth",
            "financial success", "career astrology"
        ],
        "url": f"{SITE}/career-money/career-money-astrology",
        "label": "💼 Career & Business",
    },

    "wealth_finance": {
        "keywords": [
            "wealth", "money", "finance", "financial", "debt", "loan",
            "investment", "property", "land", "real estate",
            "financial problem", "money problem", "poverty",
            "wealth astrology", "financial remedy"
        ],
        "url": f"{SITE}/wealth-finance/wealth-finance-astrology",
        "label": "💰 Wealth & Finance",
    },

    "health_astrology": {
        "keywords": [
            "health", "disease", "illness", "sickness", "healing",
            "medical", "doctor", "hospital", "treatment", "recovery",
            "health problem", "chronic illness", "health astrology",
            "ayurveda", "healing remedy"
        ],
        "url": f"{SITE}/beauty-health/beauty-health-astrology",
        "label": "🩺 Health Astrology",
    },

    "dosha_remedy": {
        "keywords": [
            "dosha", "dosham", "pariharam", "dosha remedy", "dosha pariharam",
            "mangal dosha", "manglik", "kaal sarp dosha", "kalsarp",
            "pitra dosha", "shrapit dosha", "grahan dosha",
            "guru chandal", "chandal dosha", "sade sati",
            "ashtama shani", "ezhara sani"
        ],
        "url": f"{SITE}/dosha-pariharam/",
        "label": "🌿 Dosha Remedies",
    },

    "talk_astrologer": {
        "keywords": [
            "talk to astrologer", "speak to astrologer", "human astrologer",
            "real astrologer", "expert astrologer", "astrovedspeaks",
            "astrologer speak", "consult expert"
        ],
        "url": f"{SITE}/astrovedspeaks/",
        "label": "🔮 Talk to an Astrologer",
    },

    "all_services": {
        "keywords": [
            "all services", "all products", "everything", "what do you offer",
            "what services", "what products", "full list", "complete list",
            "browse", "explore", "show me everything"
        ],
        "url": f"{SITE}/astrology-services",
        "label": "✨ All AstroVed Services",
    },
    
    "new_service_name": {
    "keywords": ["keyword1", "keyword2", "service name"],
    "url": f"{SITE}/new-page-url",
    "label": "🆕 New Service Name",
},
}


# ============================================================
#  Subcategory keys — these beat their parent topics on ties
# ============================================================
import re as _re

_SUBCATEGORY_KEYS = {
    "planetary_fire_lab", "deity_fire_lab", "purpose_fire_lab",
    "planetary_pooja", "deity_pooja", "purpose_pooja",
    "tarpanam", "kerala_remedy", "kerala_remedies_all",
    "nadi_chapters", "vishnu_maya", "agastya_reading",
    "yantra_gods", "yantra_goddess", "yantra_planets",
    "mala_gods", "mala_goddess", "mala_planets", "special_malas",
    "statue_gods", "statue_goddess", "statue_planets",
    "pendant_gods", "pendant_goddess", "pendant_planets",
    "bracelet_planets",
    "amulet_wealth", "amulet_success", "amulet_protection",
    "amulet_health", "amulet_planetary", "amulet_relationship",
    "planet_incense",
    "horoscope", "birth_chart", "horoscope_matching",
    "numerology", "gemstone_tool", "vastu", "palmistry",
    "free_reports", "ask_astrologer", "customized_reports",
    "live_consultation", "prasna", "electional_astrology",
}


# ============================================================
#  match_topic() — import this in main.py
#  Usage: url, label = match_topic(user_message)
# ============================================================
def match_topic(user_message: str):
    """
    Scores every keyword match:
      base  = keyword length × 10
      +15   whole-word match
      +20   subcategory topic (more specific than parent)
    Returns (url, label) or (None, None).
    """
    text = user_message.lower().strip()
    best_data = None
    best_score = 0

    for topic_key, topic_data in TOPIC_MAP.items():
        for kw in topic_data["keywords"]:
            if kw in text:
                score = len(kw) * 10
                if _re.search(r'\b' + _re.escape(kw) + r'\b', text):
                    score += 15
                if topic_key in _SUBCATEGORY_KEYS:
                    score += 20
                if score > best_score:
                    best_score = score
                    best_data = topic_data

    if best_data:
        return best_data["url"], best_data["label"]
    return None, None


# ============================================================
#  Quick test — run: python topic_map.py
# ============================================================
if __name__ == "__main__":
    tests = [
        ("I want to know about malas",            "📿 Browse All Malas"),
        ("tell me about rudraksha mala",           "📿 Browse All Malas"),
        ("aquamarine mala",                        "📿 Browse All Malas"),
        ("I need a homa for saturn",               "🔥 Fire Lab (Homa)"),
        ("saturn fire lab",                        "🪐 Planetary Fire Lab"),
        ("ganesha fire lab",                       "🕉️ Archetype (Deity) Fire Lab"),
        ("what is nadi astrology",                 "📜 Nadi Astrology"),
        ("I have mangal dosha",                    "🌿 Dosha Remedies"),
        ("show me yantras",                        "🔱 Yantras"),
        ("jupiter yantra",                         "🪐 Planetary Yantras"),
        ("I want to buy a bracelet",               "⚜️ Bracelets"),
        ("copper amulet for wealth",               "🥉 Energized Copper Amulet"),
        ("wealth boosting amulet",                 "💰 Wealth Boosting Amulet"),
        ("live consultation with astrologer",      "📞 Live Astrology Consultation"),
        ("free birth chart",                       "📊 Free Birth Chart"),
        ("horoscope for today",                    "🌙 Daily Horoscope"),
        ("pradosham pooja",                        "🌙 Pradosham"),
        ("tarpanam ritual",                        "💧 Tarpanam"),
        ("statue of ganesha",                      "🗿 Statues / Idols"),
        ("ganesha statue",                         "🕉️ God Statues"),
        ("goddess statue",                         "🌸 Goddess Statues"),
        ("lakshmi pendant",                        "🌸 Goddess Pendants"),
        ("ask 3 questions to an astrologer",       "❓ Ask Astrologer 3 Questions"),
        ("kerala remedy",                          "🌴 Kerala Remedy"),
        ("agastya reading",                        "🔭 Agastya Live Channel Reading"),
        ("membership plan",                        "👑 Membership Plans"),
        ("mobile app download",                    "📱 Mobile Apps"),
        ("herbal incense",                         "🌿 Herbal Remedy Incense"),
        ("planet earth incense",                   "🪐 Planet Earth Incense"),
        ("planetary mala",                         "🪐 Planetary Malas"),
        ("health amulet",                          "🩺 Health Boosting Amulet"),
        ("protection amulet",                      "🛡️ Protection Boosting Amulet"),
        ("numerology reading",                     "🔢 Numerology Reading"),
        ("vastu for home",                         "🏠 Vastu Shastra"),
        ("palmistry report",                       "🖐️ Palm Reading Report"),
        ("sade sati",                              "🌿 Dosha Remedies"),
        ("kalsarp dosha",                          "🌿 Dosha Remedies"),
        ("nadi chapters",                          "📖 Nadi Chapters"),
        ("love problem",                           "❤️ Love & Relationships"),
        ("career astrology",                       "💼 Career & Business"),
    ]
    passed = failed = 0
    for q, expected in tests:
        url, label = match_topic(q)
        ok = label == expected
        passed += ok; failed += not ok
        print(f"{'✅' if ok else '❌'} {q!r:50s} → {label}")
    print(f"\n{'='*60}")
    print(f"Result: {passed}/{len(tests)} passed")
    
