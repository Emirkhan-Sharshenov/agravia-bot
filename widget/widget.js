/**
 * AGRAVIA AI chat widget «Алиса»
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
    history: [],          // [{role, content}]
    open: false,
  };

  // ---------- styles ----------
  var css = `
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
  .agv-close{margin-left:auto;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;line-height:1;}
  .agv-body{flex:1;overflow-y:auto;padding:14px;background:#FAFAF7;display:flex;flex-direction:column;gap:10px;}
  .agv-msg{max-width:85%;padding:9px 12px;border-radius:12px;font-size:13.5px;line-height:1.45;white-space:pre-wrap;}
  .agv-msg.bot{background:#EDF3EA;color:#1F2A1C;align-self:flex-start;border-bottom-left-radius:2px;}
  .agv-msg.user{background:#2F6B3E;color:#fff;align-self:flex-end;border-bottom-right-radius:2px;}
  .agv-choices{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;}
  .agv-choice-btn{border:1px solid #2F6B3E;color:#2F6B3E;background:#fff;border-radius:20px;
    padding:7px 12px;font-size:13px;cursor:pointer;transition:background .15s;}
  .agv-choice-btn:hover{background:#EDF3EA;}
  .agv-footer{border-top:1px solid #eee;padding:10px;display:flex;gap:8px;background:#fff;}
  .agv-input{flex:1;border:1px solid #ddd;border-radius:20px;padding:9px 14px;font-size:13.5px;outline:none;}
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
    '  <div><div class="agv-title">Алиса</div><div class="agv-sub">помощник AGRAVIA</div></div>' +
    '  <button class="agv-close" aria-label="Закрыть">×</button>' +
    "</div>" +
    '<div class="agv-body"></div>' +
    '<div class="agv-footer">' +
    '  <input class="agv-input" type="text" placeholder="Напишите вопрос..." />' +
    '  <button class="agv-send" aria-label="Отправить">➤</button>' +
    "</div>";

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  var body = panel.querySelector(".agv-body");
  var input = panel.querySelector(".agv-input");
  var sendBtn = panel.querySelector(".agv-send");
  var closeBtn = panel.querySelector(".agv-close");

  function scrollDown() {
    body.scrollTop = body.scrollHeight;
  }

  function addMessage(text, who) {
    var div = document.createElement("div");
    div.className = "agv-msg " + who;
    div.textContent = text;
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
      t.textContent = "Алиса печатает…";
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
    form.querySelector("button").onclick = function () {
      var name = form.querySelector(".agv-name").value.trim();
      var contact = form.querySelector(".agv-contact").value.trim();
      if (!name || !contact) return;
      form.remove();
      sendHandoff(name, contact, question);
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

  function sendHandoff(name, contact, question) {
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
      .then(function () {
        addMessage("Спасибо! Менеджер свяжется с вами в ближайшее время.", "bot");
      })
      .catch(function () {
        addMessage("Не удалось отправить заявку. Попробуйте написать нам напрямую.", "bot");
      });
  }

  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    addMessage(text, "user");
    state.history.push({ role: "user", content: text });
    setTyping(true);
    sendBtn.disabled = true;

    fetch(API_BASE + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        message: text,
        history: state.history.slice(0, -1), // без последнего user-сообщения, оно уже в message
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.sessionId = data.session_id;
        state.segment = data.segment;
        setTyping(false);
        sendBtn.disabled = false;
        addMessage(data.reply, "bot");
        state.history.push({ role: "assistant", content: data.reply });
        if (data.offer_manager) {
          askHandoffConsent(text);
        }
      })
      .catch(function () {
        setTyping(false);
        sendBtn.disabled = false;
        addMessage("Произошла ошибка соединения. Попробуйте ещё раз.", "bot");
      });
  }

  sendBtn.onclick = sendMessage;
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendMessage();
  });

  launcher.onclick = function () {
    state.open = !state.open;
    panel.style.display = state.open ? "flex" : "none";
    if (state.open && body.children.length === 0) showGreeting();
  };
  closeBtn.onclick = function () {
    state.open = false;
    panel.style.display = "none";
  };
})();
