/**
 * AGRAVIA AI chat widget «ИИ-помощник АГРАВИИ»
 * Подключение на сайте:
 *   <script src="https://YOUR_BACKEND_HOST/widget/widget.js"
 *           data-api="https://YOUR_BACKEND_HOST/api"></script>
 */
(function () {
  "use strict";

  var scriptTag = document.currentScript;
  var API_BASE = (scriptTag && scriptTag.getAttribute("data-api")) || "/api";

  var state = {
    sessionId: null,
    segment: null,        // определяется бэкендом автоматически (common/visitor/exhibitor/uncertain)
    convState: null,      // состояние диалога (роль, тема, уточнение): приходит от бэкенда и отправляется обратно
    history: [],          // [{role, content}]
    open: false,
  };

  // ---------- styles ----------
  var css = `
  .agv-panel,.agv-panel *,.agv-launcher{box-sizing:border-box;}
  .agv-launcher,.agv-send,.agv-close{padding:0;margin:0;min-width:0;}
  .agv-launcher{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;
    background:#2F6B3E;color:#fff;border:none;box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer;
    display:flex;align-items:center;justify-content:center;z-index:999999;transition:transform .15s ease;}
  .agv-launcher:hover{transform:scale(1.06);}
  .agv-launcher svg{width:28px;height:28px;}
  .agv-panel{position:fixed;right:20px;bottom:92px;width:360px;max-width:calc(100vw - 40px);
    height:520px;max-height:calc(100vh - 140px);background:#fff;border-radius:16px;
    box-shadow:0 12px 40px rgba(0,0,0,.3);display:flex;flex-direction:column;overflow:hidden;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;z-index:999999;}
  .agv-header{background:#2F6B3E;color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px;}
  .agv-header .agv-avatar{width:32px;height:32px;border-radius:50%;background:#F2A93B;
    display:flex;align-items:center;justify-content:center;font-weight:700;color:#26421C;}
  .agv-header .agv-title{font-weight:600;font-size:15px;line-height:1.2;}
  .agv-header .agv-sub{font-size:12px;opacity:.85;}
  .agv-header{flex-shrink:0;}
  .agv-header-copy{flex:1;min-width:0;}
  .agv-settings-btn,.agv-close{flex-shrink:0;background:none;border:none;color:#fff;cursor:pointer;line-height:1;width:28px;height:28px;padding:0;display:flex;align-items:center;justify-content:center;}
  .agv-close{font-size:22px;}
  .agv-settings-btn{position:relative;}
  .agv-settings-btn svg{width:20px;height:20px;}
  .agv-settings-btn[data-recording="true"]:after{content:"";position:absolute;right:0;top:1px;width:7px;height:7px;background:#D7F5A8;border-radius:50%;}
  .agv-settings-btn:focus-visible,.agv-close:focus-visible{outline:2px solid #fff;outline-offset:2px;}
  .agv-settings{flex:1;min-height:0;overflow-y:auto;padding:20px 16px;color:#1F2A1C;background:#FAFAF7;font-size:13px;line-height:1.5;}
  .agv-settings[hidden],.agv-settings-btn[hidden],.agv-body[hidden],.agv-footer[hidden]{display:none;}
  .agv-settings h3{font-size:16px;margin:0 0 16px;}
  .agv-settings label{display:flex;gap:10px;align-items:flex-start;cursor:pointer;}
  .agv-settings input{flex-shrink:0;width:18px;height:18px;margin:2px 0 0;accent-color:#2F6B3E;}
  .agv-settings p{margin:12px 0;color:#52604E;}
  .agv-settings a{color:#1c5a2c;text-decoration:underline;}
  .agv-settings-done{display:block;margin-top:20px;border:0;border-radius:20px;padding:9px 18px;background:#2F6B3E;color:#fff;cursor:pointer;font-size:13px;}
  .agv-research-invite{flex-shrink:0;margin:0 10px 8px;padding:11px 12px 9px;border:1px solid #e0e9da;border-radius:12px;background:linear-gradient(120deg,#f4f8f0,#fcfdfb);color:#30452b;font-size:12px;line-height:1.4;}
  .agv-research-invite[hidden]{display:none;}
  .agv-research-invite label{display:flex;align-items:flex-start;gap:10px;cursor:pointer;}
  .agv-research-invite input{appearance:none;-webkit-appearance:none;flex-shrink:0;display:grid;place-content:center;width:20px;height:20px;padding:0;margin:1px 0 0;border:1.5px solid #8da582;border-radius:6px;background:#fff;cursor:pointer;transition:background .15s,border-color .15s;}
  .agv-research-invite input:checked{background:#2F6B3E;border-color:#2F6B3E;}
  .agv-research-invite input:checked:after{content:"";width:5px;height:9px;border:solid #fff;border-width:0 2px 2px 0;transform:translateY(-1px) rotate(45deg);}
  .agv-research-invite input:focus-visible{outline:2px solid #2F6B3E;outline-offset:3px;}
  .agv-research-copy{min-width:0;}
  .agv-research-copy strong{display:block;font-size:13px;font-weight:600;letter-spacing:0;}
  .agv-research-copy small{display:block;margin-top:2px;color:#56654e;font-size:11.5px;line-height:1.4;}
  .agv-research-invite .agv-research-actions{display:flex;align-items:center;justify-content:space-between;margin:6px 0 0 30px;gap:8px;}
  .agv-research-invite a,.agv-research-invite button{font:inherit;font-size:11.5px;color:#526d49;text-decoration:none;}
  .agv-research-invite a{text-decoration:underline;text-underline-offset:3px;text-decoration-color:#afc0a7;}
  .agv-research-invite button{border:0;border-radius:6px;background:transparent;padding:3px 6px;margin-right:-6px;cursor:pointer;}
  .agv-research-invite button:hover{background:#e7efdf;}
  .agv-footer{flex-shrink:0;}
  .agv-body{flex:1;min-height:0;overflow-y:auto;padding:14px;background:#FAFAF7;display:flex;flex-direction:column;gap:10px;}
  .agv-msg{max-width:85%;padding:9px 12px;border-radius:12px;font-size:13.5px;line-height:1.45;white-space:pre-wrap;}
  .agv-msg.bot{background:#EDF3EA;color:#1F2A1C;align-self:flex-start;border-bottom-left-radius:2px;}
  .agv-msg a{color:#1c5a2c;text-decoration:underline;word-break:normal;overflow-wrap:anywhere;}
    .agv-msg.user{background:#2F6B3E;color:#fff;align-self:flex-end;border-bottom-right-radius:2px;}
  .agv-choices{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;}
  .agv-choice-btn{border:1px solid #2F6B3E;color:#2F6B3E;background:#fff;border-radius:20px;
    padding:7px 12px;font-size:13px;cursor:pointer;transition:background .15s;}
  .agv-choice-btn:hover{background:#EDF3EA;}
  .agv-footer{border-top:1px solid #eee;padding:10px;display:flex;gap:8px;background:#fff;}
  .agv-input{flex:1;min-width:0;border:1px solid #ddd;border-radius:20px;padding:9px 14px;font-size:13.5px;outline:none;}
  .agv-input:focus{border-color:#2F6B3E;}
  .agv-send{background:#2F6B3E;color:#fff;border:none;border-radius:50%;width:38px;height:38px;
    cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
  .agv-send:disabled{opacity:.5;cursor:default;}
  .agv-typing{font-size:12px;color:#888;padding-left:4px;}
  .agv-form{display:flex;flex-direction:column;gap:8px;background:#EDF3EA;padding:12px;border-radius:12px;}
  .agv-form input{border:1px solid #ccc;border-radius:8px;padding:8px 10px;font-size:13px;}
  .agv-form button{background:#2F6B3E;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;cursor:pointer;}
  `;
  var styleTag = document.createElement("style");
  styleTag.textContent = css;
  document.head.appendChild(styleTag);

  // ---------- DOM scaffold ----------
  var launcher = document.createElement("button");
  launcher.className = "agv-launcher";
  launcher.setAttribute("aria-label", "Открыть чат AGRAVIA");
  launcher.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';

  var panel = document.createElement("div");
  panel.className = "agv-panel";
  panel.style.display = "none";
  panel.innerHTML =
    '<div class="agv-header">' +
    '  <div class="agv-avatar">А</div>' +
    '  <div class="agv-header-copy"><div class="agv-title">ИИ-помощник АГРАВИИ</div><div class="agv-sub">Выставка AGRAVIA</div></div>' +
    '  <button class="agv-settings-btn" aria-label="Настройки чата" aria-expanded="false" aria-controls="agv-chat-settings" title="Настройки чата" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z"/><circle cx="12" cy="12" r="3"/></svg></button>' +
    '  <button class="agv-close" aria-label="Закрыть">×</button>' +
    "</div>" +
    '<div class="agv-body"></div>' +
    '<div class="agv-footer">' +
    '  <input class="agv-input" type="text" maxlength="4000" placeholder="Напишите вопрос..." />' +
    '  <button class="agv-send" aria-label="Отправить">➤</button>' +
    "</div>";

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  var body = panel.querySelector(".agv-body");
  var input = panel.querySelector(".agv-input");
  var sendBtn = panel.querySelector(".agv-send");
  var closeBtn = panel.querySelector(".agv-close");
  var settingsBtn = panel.querySelector(".agv-settings-btn");
  var settingsView = null;
  var researchInvite = null;
  var footer = panel.querySelector(".agv-footer");
  function showSettings(open) {
    if (!settingsView) return;
    settingsView.hidden = !open;
    if (open && researchInvite) researchInvite.hidden = true;
    body.hidden = open;
    footer.hidden = open;
    settingsBtn.setAttribute("aria-expanded", String(open));
    if (open) researchChoice.focus();
    else settingsBtn.focus();
  }
  settingsBtn.onclick = function () { showSettings(settingsBtn.getAttribute("aria-expanded") !== "true"); };
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && settingsView && !settingsView.hidden) {
      showSettings(false); event.stopPropagation();
    }
  });
  var researchChoice = null;
  var researchVersion = null;
  var researchConfigLoaded = false;

  function loadResearchChoice() {
    if (researchConfigLoaded) return;
    researchConfigLoaded = true;
    fetch(API_BASE + "/research-config")
      .then(function (r) { if (!r.ok) throw new Error("config unavailable"); return r.json(); })
      .then(function (cfg) {
        if (!cfg.enabled || !cfg.notice_url) return;
        var url = new URL(cfg.notice_url);
        if (url.protocol !== "https:" || (url.hostname !== "agravia.org" &&
            url.hostname !== "d5daon1oep4l58a9tuca.jki8ffxa.apigw.yandexcloud.net")) return;
        researchVersion = cfg.notice_version;
        var wrap = document.createElement("div");
        wrap.className = "agv-settings";
        wrap.id = "agv-chat-settings";
        wrap.hidden = true;
        var heading = document.createElement("h3");
        heading.textContent = "Запись для улучшения ответов";
        wrap.appendChild(heading);
        var label = document.createElement("label");
        researchChoice = document.createElement("input");
        researchChoice.type = "checkbox";
        researchChoice.checked = false;
        label.appendChild(researchChoice);
        label.appendChild(document.createTextNode("Разрешаю сохранять сообщения этого чата для проверки и улучшения ответов на срок до 30 дней. "));
        var link = document.createElement("a");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.textContent = "Условия обработки";
        wrap.appendChild(label);
        var note = document.createElement("p");
        note.textContent = "Выключено по умолчанию. Можно пользоваться помощником без записи для анализа. После снятия галочки следующие сообщения не сохраняются в архив проверки; для удаления прежних записей используйте контакт в условиях.";
        wrap.appendChild(note);
        wrap.appendChild(link);
        var caution = document.createElement("p");
        caution.textContent = "Не присылайте личные и секретные данные.";
        wrap.appendChild(caution);
        var done = document.createElement("button");
        done.className = "agv-settings-done";
        done.textContent = "Вернуться к чату";
        done.onclick = function () { showSettings(false); input.focus(); };
        wrap.appendChild(done);
        panel.insertBefore(wrap, footer);
        settingsView = wrap;
        settingsBtn.hidden = false;
        function updateResearchChoice() {
          settingsBtn.setAttribute("data-recording", String(researchChoice.checked));
          settingsBtn.title = researchChoice.checked ? "Настройки чата: запись для анализа включена" : "Настройки чата: запись для анализа выключена";
          if (researchInvite) researchInvite.hidden = true;
          showSettings(false);
        }
        researchChoice.addEventListener("change", updateResearchChoice);

        researchInvite = document.createElement("div");
        researchInvite.className = "agv-research-invite";
        var inviteLabel = document.createElement("label");
        var inviteChoice = document.createElement("input");
        inviteChoice.type = "checkbox";
        inviteChoice.checked = false;
        inviteLabel.appendChild(inviteChoice);
        var inviteCopy = document.createElement("span");
        inviteCopy.className = "agv-research-copy";
        var inviteTitle = document.createElement("strong");
        inviteTitle.textContent = "Помочь улучшить ответы";
        var inviteDescription = document.createElement("small");
        inviteDescription.textContent = "Разрешаю запись этого чата до 30 дней.";
        inviteCopy.appendChild(inviteTitle);
        inviteCopy.appendChild(inviteDescription);
        inviteLabel.appendChild(inviteCopy);
        researchInvite.appendChild(inviteLabel);
        var actions = document.createElement("div");
        actions.className = "agv-research-actions";
        var inviteLink = document.createElement("a");
        inviteLink.href = url.href; inviteLink.target = "_blank"; inviteLink.rel = "noopener noreferrer";
        inviteLink.textContent = "Как используются сообщения";
        actions.appendChild(inviteLink);
        var skip = document.createElement("button");
        skip.textContent = "Не сейчас";
        skip.onclick = function () { researchInvite.hidden = true; input.focus(); };
        actions.appendChild(skip);
        researchInvite.appendChild(actions);
        inviteChoice.addEventListener("change", function () {
          researchChoice.checked = inviteChoice.checked;
          updateResearchChoice();
          input.focus();
        });
        panel.insertBefore(researchInvite, footer);
      })
      .catch(function () { /* Missing config never enables research recording. */ });
  }

  function scrollDown() {
    body.scrollTop = body.scrollHeight;
  }

  // Ссылки в ответах бота — кликабельные (ТЗ 28.10: «давать кликабельную прямую
  // ссылку»). Только http(s), через DOM-узлы и textContent — без innerHTML, чтобы
  // текст ответа не мог вставить разметку. Завершающая пунктуация в ссылку не входит.
  function appendLinkified(el, text) {
    var re = /https?:\/\/[^\s]+/g, last = 0, m;
    while ((m = re.exec(text)) !== null) {
      var url = m[0], trail = "";
      var t = url.match(/[.,;:!?)»"'”]+$/);
      if (t) { trail = t[0]; url = url.slice(0, url.length - trail.length); }
      el.appendChild(document.createTextNode(text.slice(last, m.index)));
      var a = document.createElement("a");
      a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = url;
      try {
        var parsed = new URL(url);
        var labels = {'/reg':'Регистрация','/reg_en':'Registration','/participants':'Каталог участников','/program':'Деловая программа','/organizer':'Контакты организатора','/competition':'Конкурс','/tourist':'Поездка и приглашение','/book1':'Заявка на участие'};
        if (!/[А-Яа-яЁё]/.test(text)) {
          labels = /[\u4e00-\u9fff]/.test(text)
            ? {'/reg':'参观登记','/reg_en':'参观登记','/participants':'参展商名录','/program':'活动日程','/organizer':'联系主办方','/competition':'评选活动','/tourist':'旅行与邀请函','/book1':'参展申请'}
            : {'/reg':'Registration','/reg_en':'Registration','/participants':'Exhibitor catalog','/program':'Business program','/organizer':'Organizer contacts','/competition':'Competition','/tourist':'Travel and invitations','/book1':'Exhibitor application'};
        }
        if (parsed.hostname === 'agravia.org' && !parsed.search && !parsed.hash) {
          a.textContent = labels[parsed.pathname] || parsed.hostname + parsed.pathname;
          a.title = url;
        }
      } catch (_) { /* Keep the original text for an unexpected URL. */ }
      el.appendChild(a);
      if (trail) el.appendChild(document.createTextNode(trail));
      last = m.index + m[0].length;
    }
    el.appendChild(document.createTextNode(text.slice(last)));
  }

  function addMessage(text, who) {
    var div = document.createElement("div");
    div.className = "agv-msg " + who;
    if (who === "bot") appendLinkified(div, text);
    else div.textContent = text;
    body.appendChild(div);
    scrollDown();
    return div;
  }

  function addChoices(options) {
    var wrap = document.createElement("div");
    wrap.className = "agv-choices";
    options.forEach(function (opt) {
      var btn = document.createElement("button");
      btn.className = "agv-choice-btn";
      btn.textContent = opt.label;
      btn.onclick = opt.onClick;
      wrap.appendChild(btn);
    });
    body.appendChild(wrap);
    scrollDown();
    return wrap;
  }

  function setTyping(on) {
    var existing = body.querySelector(".agv-typing");
    if (on && !existing) {
      var t = document.createElement("div");
      t.className = "agv-typing";
      t.textContent = "Помощник печатает…";
      body.appendChild(t);
      scrollDown();
    } else if (!on && existing) {
      existing.remove();
    }
  }

  // Раздел 17 ТЗ: обязательный выбор роли перед стартом диалога убран.
  // Свободный ввод работает сразу; быстрые кнопки — просто подсказка,
  // при нажатии они отправляют обычное сообщение через тот же sendMessage,
  // сегмент бэкенд определит сам.
  var QUICK_REPLIES = [
    "Как получить билет?",
    "Даты выставки",
    "Деловая программа",
    "Хочу стать участником",
    "Вопрос по стенду",
  ];

  function showGreeting() {
    addMessage(
      "Здравствуйте! Я помощник AGRAVIA. Могу помочь с посещением выставки, " +
        "билетами, программой, участием, стендами, монтажом и другими " +
        "вопросами. Просто напишите, что хотите узнать.",
      "bot"
    );
    addChoices(
      QUICK_REPLIES.map(function (label) {
        return {
          label: label,
          onClick: function () {
            var lastChoices = body.querySelectorAll(".agv-choices");
            if (lastChoices.length) lastChoices[lastChoices.length - 1].remove();
            input.value = label;
            sendMessage();
          },
        };
      })
    );
    input.focus();
  }

  function offerHandoffForm(question) {
    var form = document.createElement("div");
    form.className = "agv-form";
    form.innerHTML =
      '<input class="agv-name" placeholder="Ваше имя" />' +
      '<input class="agv-contact" placeholder="Телефон или e-mail" />' +
      "<button>Отправить менеджеру</button>";
    body.appendChild(form);
    scrollDown();
    var btn = form.querySelector("button");
    btn.onclick = function () {
      var name = form.querySelector(".agv-name").value.trim();
      var contact = form.querySelector(".agv-contact").value.trim();
      if (!name || !contact) return;
      btn.disabled = true;
      btn.textContent = "Отправляем…";
      // Форма остаётся на экране, пока сервер не подтвердил доставку: при
      // ошибке введённые данные не пропадают и можно повторить.
      sendHandoff(name, contact, question, function () {
        form.remove();
      }, function () {
        btn.disabled = false;
        btn.textContent = "Отправить менеджеру";
      });
    };
  }

  function askHandoffConsent(question) {
    addChoices([
      {
        label: "Да, соединить с менеджером",
        onClick: function () {
          body.querySelectorAll(".agv-choices").forEach(function (n) { n.remove(); });
          offerHandoffForm(question);
        },
      },
      {
        label: "Нет, задать другой вопрос",
        onClick: function () {
          body.querySelectorAll(".agv-choices").forEach(function (n) { n.remove(); });
          input.focus();
        },
      },
    ]);
  }

  function sendHandoff(name, contact, question, onSuccess, onFail) {
    fetch(API_BASE + "/handoff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId || "",
        segment: state.segment || "uncertain",
        name: name,
        contact: contact,
        question: question,
      }),
    })
      .then(function (r) {
        // "Отправлено" — только если сервер подтвердил доставку (HTTP 2xx).
        if (!r.ok) throw new Error("handoff failed: " + r.status);
        onSuccess();
        addMessage("Спасибо! Менеджер свяжется с вами в ближайшее время.", "bot");
      })
      .catch(function () {
        onFail();
        addMessage(
          "Не удалось отправить заявку — попробуйте ещё раз чуть позже или свяжитесь с организатором напрямую: +7 (495) 128 29 59.",
          "bot"
        );
      });
  }

  function sendMessage() {
    if (sendBtn.disabled) return;
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    addMessage(text, "user");
    state.history.push({ role: "user", content: text });
    setTyping(true);
    sendBtn.disabled = true;
    var controller = new AbortController();
    var requestTimer = setTimeout(function () { controller.abort(); }, 35000);

    fetch(API_BASE + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        session_id: state.sessionId,
        state: state.convState, // роль/тема/уточнение — бэкенд ничего не хранит, состояние носит клиент
        message: text,
        history: state.history.slice(0, -1).slice(-20),
        research_consent: Boolean(researchChoice && researchChoice.checked),
        research_notice_version: researchChoice && researchChoice.checked ? researchVersion : null,
      }),
    })
      .then(function (r) {
        if (!r.ok) { var error = new Error("chat request failed"); error.status = r.status; throw error; }
        return r.json();
      })
      .then(function (data) {
        if (typeof data.reply !== "string" || !data.reply.trim()) throw new Error("empty reply");
        clearTimeout(requestTimer);
        state.sessionId = data.session_id;
        state.segment = data.segment;
        state.convState = data.state || null;
        setTyping(false);
        sendBtn.disabled = false;
        addMessage(data.reply, "bot");
        state.history.push({ role: "assistant", content: data.reply });
        if (data.offer_manager) {
          askHandoffConsent(text);
        }
      })
      .catch(function (error) {
        clearTimeout(requestTimer);
        setTyping(false);
        sendBtn.disabled = false;
        if (state.history.length && state.history[state.history.length - 1].role === "user") state.history.pop();
        var message = error.status === 429 || error.status === 503 || error.name === "AbortError"
          ? "Сейчас помощник занят или отвечает слишком долго. Попробуйте через минуту."
          : error.status === 422 || error.status === 413
          ? "Пожалуйста, сократите вопрос и попробуйте ещё раз."
          : "Не удалось получить ответ. Попробуйте ещё раз чуть позже.";
        addMessage(message + " Регистрация: https://agravia.org/reg. Контакты организатора: https://agravia.org/organizer.", "bot");
      });
  }

  sendBtn.onclick = sendMessage;
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendMessage();
  });

  launcher.onclick = function () {
    state.open = !state.open;
    panel.style.display = state.open ? "flex" : "none";
    if (state.open) loadResearchChoice();
    if (state.open && body.children.length === 0) showGreeting();
  };
  closeBtn.onclick = function () {
    state.open = false;
    panel.style.display = "none";
  };
})();

