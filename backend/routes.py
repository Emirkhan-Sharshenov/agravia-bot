"""
Единый справочник маршрутов (ТЗ от 28.10.2026, раздел 6.1): intent -> основной URL
-> краткий шаблон ответа. Ссылки и контакты живут ТОЛЬКО здесь — не дублируются в
промптах и других файлах. Адреса — из комментариев Егора к QA-набору; содержимое
страниц в рамках разработки не проверялось (перед публикацией перепроверить).

Шаблонные ответы детерминированы: правильная ссылка выдаётся всегда, ничего не
выдумывается, и для них не нужен вызов ответной модели (экономия токенов и
устойчивость к лимитам провайдера). Тексты — ориентир по смыслу из ТЗ; для
вопросов, где нужны детали из базы знаний, ответ формирует модель, а ссылка
дописывается из этого же справочника (см. LINK_AFTER).
"""
from __future__ import annotations

LINKS = {
    "reg": "https://agravia.org/reg",
    "reg_en": "https://agravia.org/reg_en",
    "iagri_reg": "https://iagri-expo.com/reg",
    "book1": "https://agravia.org/book1",
    "participants": "https://agravia.org/participants",
    "program": "https://agravia.org/program",
    "banners": "https://agravia.org/banners",
    "content_liga": "https://agravia.org/content_liga",
    "exhibitors_video": "https://agravia.org/exhibitors-video",
    "competition": "https://agravia.org/competition",
    "organizer": "https://agravia.org/organizer",
    "feedhealth": "https://agravia.org/feedhealth",
    "hortilandscape": "https://agravia.org/hortilandscape",
    "tourist": "https://agravia.org/tourist",
    "policy": "https://agravia.org/policy",
}

ORGANIZER_PHONE = "+7 (495) 128-29-59"
SUPPORT_CONTACT = "agravia@expodat.com, +7 (499) 758-0-911 (пн–пт, 10:00–18:00 МСК)"
SUPPORT_CONTACT_EN = "agravia@expodat.com, +7 (499) 758-0-911 (Mon–Fri, 10:00–18:00 Moscow time)"

# Ссылка, которая дописывается после ответа модели по базе знаний для темы.
LINK_AFTER = {
    "ticket_info": ("reg", "Регистрация: {url}", "Registration: {url}"),
}

# Шаблоны: intent -> {"ru": ..., "en": ...}. Плейсхолдеры {ключ} берутся из LINKS и
# констант выше. Если английского варианта нет — используется русский.
TEMPLATES: dict[str, dict[str, str]] = {
    "dates": {
        "ru": "AGRAVIA 2027 пройдёт 20–22 января 2027 года в МВЦ «Крокус Экспо», павильон 3. "
              "Часы работы: 20 и 21 января — 09:00–18:00, 22 января — 09:00–16:00.",
        "en": "AGRAVIA 2027 will take place on 20–22 January 2027 at Crocus Expo, Pavilion 3. "
              "Opening hours: 20–21 January 09:00–18:00, 22 January 09:00–16:00.",
    },
    "visitor_registration": {
        "ru": "Для посещения AGRAVIA зарегистрируйтесь бесплатно: {reg}. "
              "Электронный билет можно сохранить на телефоне — распечатывать необязательно.",
        "en": "To visit AGRAVIA, register for free: {reg_en}. "
              "The e-ticket can be saved on your phone — printing is not required.",
    },
    "iagri_registration": {
        "ru": "Для посещения iAGRI зарегистрируйтесь здесь: {iagri_reg}. "
              "Один билет действует и на AGRAVIA, и на iAGRI.",
        "en": "To visit iAGRI, register here: {iagri_reg}. One ticket is valid for both AGRAVIA and iAGRI.",
    },
    "reg_support": {
        "ru": "По вопросам регистрации (не пришло письмо, ошибка в e-mail, не получается получить билет) "
              "обратитесь в техническую поддержку регистрации: {support}.",
        "en": "For registration problems (no email received, wrong email, can't get a ticket) "
              "please contact registration technical support: {support_en}.",
    },
    "participation": {
        "ru": "Чтобы участвовать со стендом, заполните заявку: {book1}. После отправки с вами свяжется "
              "менеджер, уточнит задачу и предложит подходящие условия. Стоимость зависит от формата "
              "участия и рассчитывается индивидуально.",
        "en": "To exhibit with a stand, please fill in the application: {book1}. After you submit it, a manager "
              "will contact you, clarify your needs and offer suitable conditions. The price depends on the "
              "participation format and is calculated individually.",
    },
    "exhibit_or_visit": {
        "ru": "Если вы хотите участвовать со стендом — заполните заявку: {book1}, затем с вами свяжется менеджер. "
              "Если нужен билет посетителя — регистрация бесплатная: {reg}.",
        "en": "To exhibit with a stand, fill in the application: {book1} — a manager will contact you afterwards. "
              "To visit as a guest, register for free: {reg_en}.",
    },
    "stand_find_or_book": {
        "ru": "Если вы хотите участвовать со стендом — заявка: {book1}. "
              "Если ищете стенд конкретного участника — каталог участников: {participants}.",
        "en": "To exhibit with a stand — application: {book1}. "
              "To find a particular exhibitor's stand — participants catalog: {participants}.",
    },
    "catalog": {
        "ru": "Актуальный список участников AGRAVIA 2027: {participants}. Он пополняется; номера стендов и схема "
              "залов появятся ближе к выставке. Подтвердить участие конкретной компании или номер стенда "
              "я не могу — посмотрите, пожалуйста, в списке.",
        "en": "The current list of AGRAVIA 2027 participants: {participants}. It keeps being updated; stand numbers "
              "and the hall map will appear closer to the event. I can't confirm a specific company or stand "
              "number myself — please check the list.",
    },
    "industry_feed": {
        "ru": "По кормам, кормовым добавкам и ветеринарии у AGRAVIA есть раздел Feed & Health: {feedhealth}. "
              "Поставщиков можно посмотреть в каталоге участников: {participants}. Решение для своей задачи "
              "можно найти и на самой выставке.",
        "en": "AGRAVIA has a dedicated Feed & Health section: {feedhealth}. You can browse suppliers in the "
              "participants catalog: {participants}.",
    },
    "industry_horti": {
        "ru": "Да, в этом году на AGRAVIA появился новый раздел Horti & Landscape — декоративное "
              "растениеводство, питомниководство, озеленение: {hortilandscape}. Участников можно посмотреть "
              "в каталоге: {participants}.",
        "en": "Yes, this year AGRAVIA has a new Horti & Landscape section — ornamental plants, nurseries, "
              "landscaping: {hortilandscape}. Participants: {participants}.",
    },
    "industry_ai": {
        "ru": "Тема нейросетей и цифровых решений для сельского хозяйства представлена на совместной площадке "
              "iAGRI, которая проходит вместе с AGRAVIA. Участников можно посмотреть в каталоге: {participants}. "
              "Один билет действует на обе выставки: {reg}.",
        "en": "AI and digital solutions for agriculture are presented at iAGRI, held together with AGRAVIA. "
              "Participants: {participants}. One ticket is valid for both shows: {reg_en}.",
    },
    "industry_other": {
        "ru": "На AGRAVIA представлены решения для всего цикла АПК: животноводство, корма и ветеринария, "
              "растениеводство, картофель, овощи и плоды, переработка. Поставщиков по вашей теме можно найти "
              "в каталоге участников: {participants}. Приехать и подобрать решение на месте можно, "
              "зарегистрировавшись бесплатно: {reg}.",
        "en": "AGRAVIA covers the whole agribusiness cycle: livestock, feed and veterinary, crops, potatoes and "
              "vegetables, processing. Find suppliers in the participants catalog: {participants}. "
              "Registration is free: {reg_en}.",
    },
    "competition": {
        "ru": "Приём заявок на конкурс «Лучший продукт AGRAVIA 2027» закрыт. Победителей объявят в конце ноября "
              "2026 года — имена будут опубликованы после объявления. Условия и номинанты: {competition}.",
        "en": "Applications for the \"Best Product AGRAVIA 2027\" competition are closed. Winners will be announced "
              "at the end of November 2026. Details and nominees: {competition}.",
    },
    "iagri_award": {
        "ru": "Премия iAGRI — отдельная награда, не связанная с конкурсом «Лучший продукт AGRAVIA». Подтверждённых "
              "условий и страницы премии у меня пока нет — уточните у организатора: {organizer_phone}, {organizer}.",
    },
    "business_program": {
        "ru": "Деловая программа AGRAVIA 2027 ещё формируется. Актуальные мероприятия, время и спикеры "
              "публикуются здесь: {program}.",
        "en": "The AGRAVIA 2027 business program is still being prepared. Current events, times and speakers "
              "are published here: {program}.",
    },
    "banners": {
        "ru": "Для приглашения клиентов можно использовать готовые баннеры AGRAVIA: {banners}.",
        "en": "You can use ready-made AGRAVIA banners to invite your clients: {banners}.",
    },
    "promo_campaign": {
        "ru": "Об акции «Встречаемся на AGRAVIA»: {content_liga} и {exhibitors_video}. Видеоформат можно "
              "использовать вместо персональной ссылки, а для клиентов — отдельные UTM-ссылки.",
    },
    "media": {
        "ru": "По аккредитации СМИ обратитесь к организатору: {organizer_phone}, {organizer}.",
        "en": "For media accreditation please contact the organizer: {organizer_phone}, {organizer}.",
    },
    "tourist": {
        "ru": "Проживание и туристические услуги: {tourist}. Контакты: Иван Иванов — +7 926 232 52 92, "
              "+7 495 231 3399 доб. 232, ivanovia@cbtc.ru; Екатерина Карманцева — +7 916 972 83 87, "
              "+7 495 231 3399 доб. 634, KarmancevaEV@cbtc.ru.",
        "en": "Accommodation and travel services: {tourist}. Contacts: Ivan Ivanov — +7 926 232 52 92, "
              "+7 495 231 3399 ext. 232, ivanovia@cbtc.ru; Ekaterina Karmantseva — +7 916 972 83 87, "
              "+7 495 231 3399 ext. 634, KarmancevaEV@cbtc.ru.",
    },
    "tourist_invite": {
        "ru": "Туристическое приглашение в РФ оформляет Николай Хоменко: +7 495 231 3399 доб. 501, "
              "agravia.invitation@cbtc.ru. Подробнее: {tourist}.",
        "en": "Tourist invitations to Russia are handled by Nikolay Khomenko: +7 495 231 3399 ext. 501, "
              "agravia.invitation@cbtc.ru. More: {tourist}.",
    },
    "contact": {
        "ru": "Связаться с организатором можно по телефону {organizer_phone}; контакты — {organizer}.",
        "en": "You can reach the organizer by phone {organizer_phone}; contacts: {organizer}.",
    },
    "materials": {
        "ru": "Уточните, пожалуйста: вам нужны материалы для приглашения клиентов (баннеры) "
              "или материалы для застройки стенда?",
    },
    "privacy_delete": {
        "ru": "Чтобы удалить свои данные, обратитесь к оператору по каналу, указанному в Политике обработки "
              "персональных данных: {policy}. Удалить данные через чат я не могу.",
        "en": "To delete your data, please contact the operator via the channel given in the Personal Data "
              "Policy: {policy}. I can't delete data through the chat.",
    },
    "privacy_storage": {
        "ru": "Точных сведений о хранении переписки и передаче данных в другие страны у меня нет, поэтому ничего "
              "не гарантирую. Актуальные условия — в Политике обработки персональных данных: {policy}; "
              "вопросы можно задать организатору: {organizer}.",
        "en": "I don't have confirmed details on message storage or cross-border transfer, so I can't promise "
              "anything. Current terms are in the Personal Data Policy: {policy}; questions: {organizer}.",
    },
    "pd_request": {
        "ru": "Я не могу показывать чужие персональные данные, в том числе телефоны зарегистрированных посетителей.",
        "en": "I can't disclose other people's personal data, including phone numbers of registered visitors.",
    },
    "secrets": {
        "ru": "Не присылайте пароль, коды и другие секреты. Если не получается получить билет, зарегистрируйтесь "
              "здесь: {reg} или обратитесь в поддержку регистрации: agravia@expodat.com.",
        "en": "Please don't send passwords, codes or other secrets. If you can't get a ticket, register here: "
              "{reg_en} or contact registration support: agravia@expodat.com.",
    },
    "greeting": {
        "ru": "Здравствуйте! Я помощник AGRAVIA. Помогу с билетом, участием и стендом, программой, монтажом "
              "и логистикой. Что вас интересует?",
        "en": "Hello! I'm the AGRAVIA assistant. I can help with tickets, exhibiting, the program and logistics. "
              "What would you like to know?",
    },
    "offtopic": {
        "ru": "Это вне моей темы — я помогаю по вопросам выставки AGRAVIA 2027: даты и место, билеты и "
              "регистрация, участие и стенды, каталог участников, деловая программа, монтаж и заезд. С чем помочь?",
        "en": "That's outside my scope — I help with AGRAVIA 2027: dates and venue, tickets, exhibiting, the "
              "participants catalog, the business program and logistics. How can I help?",
    },
    "help": {
        "ru": "Подскажите, что вам нужно: билет на выставку, участие со стендом, поиск компании или продукции, "
              "деловая программа, монтаж и заезд?",
        "en": "What do you need: a visitor ticket, exhibiting with a stand, finding a company or product, "
              "the business program, or logistics?",
    },
    "gibberish": {
        "ru": "Не поняла запрос. Попробуйте переформулировать — например, про билет, участие, каталог "
              "участников или даты.",
        "en": "I didn't understand. Please rephrase — for example, about tickets, exhibiting, the participants "
              "catalog or dates.",
    },
    "no_data": {
        "ru": "У меня нет подтверждённой информации по этому вопросу. Уточнить можно у организатора: "
              "{organizer_phone}, {organizer}.",
        "en": "I don't have confirmed information on this. Please ask the organizer: {organizer_phone}, {organizer}.",
    },
    "unavailable": {
        "ru": "Не получилось обработать запрос. Попробуйте задать его ещё раз или свяжитесь с организатором: "
              "{organizer_phone}, {organizer}.",
        "en": "I couldn't process the request. Please try again or contact the organizer: {organizer_phone}, {organizer}.",
    },
}

TEMPLATE_INTENTS = {k for k in TEMPLATES if k not in ("no_data", "unavailable")}


def _fields() -> dict[str, str]:
    fields = dict(LINKS)
    fields.update(
        organizer_phone=ORGANIZER_PHONE,
        support=SUPPORT_CONTACT,
        support_en=SUPPORT_CONTACT_EN,
    )
    return fields


def render(key: str, lang: str = "ru") -> str:
    variants = TEMPLATES[key]
    return variants.get(lang, variants["ru"]).format(**_fields())


def link_after(intent: str, lang: str = "ru") -> str | None:
    spec = LINK_AFTER.get(intent)
    if not spec:
        return None
    link_key, ru, en = spec
    key = "reg_en" if (lang == "en" and link_key == "reg") else link_key
    return (en if lang == "en" else ru).format(url=LINKS[key])
