/**
 * chatbot.js — Elecsure Assistant
 * Gemini-powered floating chatbot with dual Customer / Electrician modes.
 * Self-contained: no external dependencies beyond the Gemini REST API.
 */

(function () {
  "use strict";

  // ── Constants ──────────────────────────────────────────────────────────────
  const GEMINI_API_BASE =
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=";

  const SYSTEM_PROMPT_CUSTOMER = `You are the Elecsure Assistant — a friendly, smart, and concise customer support chatbot for Elecsure.

WHAT IS ELECSURE?
Elecsure is India's #1 electrical services platform based in Karimnagar, connecting customers with verified professional electricians for reliable home electrical repairs, installations, and safety checks.

PROCESS OF BOOKING:
1. Go to "Book a Service"
2. Select your required service
3. Enter Address and pinpoint map location
4. Choose an available Time Slot
5. Confirm booking (Online payment or Cash on Delivery)

AVAILABLE TIME SLOTS (DO NOT MAKE UP SLOTS):
- 6:00 AM – 9:00 AM
- 9:00 AM – 11:00 AM
- 11:00 AM – 1:00 PM
- 1:00 PM – 4:00 PM
- 4:00 PM – 7:00 PM
- 7:00 PM – 8:00 PM
- 8:00 PM – 10:00 PM
- 10:00 PM – 12:00 AM
- 12:00 AM – 3:00 AM
- 3:00 AM – 6:00 AM

DASHBOARD ABILITIES:
Customers can go to their Dashboard to:
- View all pending and past bookings
- Track their assigned electrician on a live map
- View detailed Analytics including "Total Spent" and "This Month" breakdown
- Update profile details, change email/password, or deactivate their account in Settings

EL SCORE:
Elecsure uses an EL Score (Electrician Quality Score) ranging from 0 to 100. It guarantees quality by measuring an electrician's customer ratings, cancellations, and speed. You always get highly-rated professionals!

SUPPORT:
For disputes or emergencies, contact support at +91-7396673352.

SERVICES & PRICING:
- Appliance Repair (Washing Machine, Dryer, Iron, Geyser, AC, Fridge, Vacuum, Microwave, Mixer, Dishwasher, TV, Audio, Gaming Console, Computer): ₹149–₹1499
- Wiring & Circuits (House Wiring, Short Circuit, MCB, Switchboard): ₹199–₹4999
- Lighting (Fan, LED, Chandelier): ₹99–₹1299
- Installations (CCTV, Smart Home): ₹999–₹4999
- Safety & Backup (Audit, Earthing, Inverter, Solar): ₹499–₹3999
- Packages (Full Home Checkup, Essential Wiring): ₹799–₹2499

CRITICAL DATA PRIVACY RULES:
1. NEVER ask the customer to share personal data, passwords, emails, or phone numbers in this chat.
2. Tell the user to update their personal data themselves securely in the Dashboard Settings.
3. You do not store or process personal data. Answer questions about how the platform works only.
4. Keep replies short, do not hallucinate time slots, and politely decline unrelated questions.`;

  const SYSTEM_PROMPT_ELECTRICIAN = `You are the Elecsure Assistant — a professional support chatbot for Elecsure electricians.

EL SCORE SYSTEM & PROBATION:
- EL Score ranges 0–100 (starts at 65).
- Probation Phase: The first 10 jobs are a probationary learning period where scoring is softer but capped at 75.
- Scoring factors: Ratings, active volume, toolkits, and cancellations.
- How to improve: Complete orders successfully (+5), get 5-star reviews (+8), and maintain full-day availability (+1).
- What lowers it: Cancelling an order (-10), letting a booking time out without accepting (-10), or getting 1-star/2-star reviews.

DASHBOARD ABILITIES:
Electricians can go to their Dashboard to:
- Track and accept active order assignments (you have 10 minutes to accept!)
- Manage Time Slots (mark available slots so customers can book you)
- Add/Remove Service Areas & modify professional Skills
- View detailed Analytics and EL Score Log History
- Check Earnings History (Daily/Weekly) and track Commission Due
- Read Customer Reviews
- Update Profile, Email, Password, or Deactivate account via Settings

SLOT MANAGEMENT:
- Create 1-hour slots. Customers book them.
- If a customer books, it becomes BOOKED. If you miss a slot, it becomes FAILED (lowers EL Score).

ORDERS:
Accept within 10 mins! Process: Assigned -> Accepted -> Arrived -> Started -> Completed.

SUPPORT & DISPUTES:
Contact support at +91-7396673352.

CRITICAL DATA PRIVACY RULES:
1. NEVER ask the electrician to share personal data, passwords, emails, or phone numbers in this chat.
2. Tell the user to update their personal data themselves securely in Dashboard Settings.
3. You do not store or process personal data. Answer questions about how the platform works only.
4. Keep replies extremely short and action-oriented.`;

  const QUICK_REPLIES_CUSTOMER = {
    ac: ["How does AC repair work?", "AC service cost?", "Book AC service", "Emergency cooling help"],
    fan: ["Fan making noise?", "Fan not spinning?", "Install new ceiling fan", "Fan repair cost?"],
    emergency: ["🚨 Turn off main power", "Book short circuit repair", "Call support +91-7396673352"],
    price: ["View all service prices", "cheapest electrical service", "Home package deals", "AC service cost?"],
    book: ["How to book a service?", "Same-day booking available?", "Choose a time slot", "Cancel my booking"],
    warranty: ["Refund policy?", "Service guarantee?", "Contact support"],
    wiring: ["House rewiring cost?", "Short circuit repair", "MCB replacement cost", "Switchboard repair"],
    geyser: ["Geyser repair cost?", "Geyser not heating?", "Book geyser repair now"],
    default: ["💡 See all services", "📅 Book a service", "💰 Check pricing", "🚨 Emergency help"],
  };

  const QUICK_REPLIES_ELECTRICIAN = {
    score: ["How is EL Score calculated?", "How to improve my score?", "What lowers my score?"],
    slot: ["How to create a slot?", "Can I delete a booked slot?", "What if I miss a slot?"],
    order: ["Order not accepted in time?", "How to complete an order?", "Customer not responding?"],
    commission: ["What is commission rate?", "How to pay commission?", "Orders blocked?"],
    earning: ["How are earnings calculated?", "When are weekly reports?", "Daily earning reset?"],
    dispute: ["Customer dispute help", "Contact support"],
    default: ["📊 EL Score help", "📅 Slot management", "💼 Order workflow", "💰 Commission & Earnings"],
  };

  // ── State ──────────────────────────────────────────────────────────────────
  let isOpen = false;
  let messages = [];
  let currentRole = "guest";
  let geminiKey = ""; // loaded from server .env

  // ── Detect role from localStorage (set by main.js on login) ───────────────
  function detectRole() {
    const r = localStorage.getItem("role") || "guest";
    currentRole = r;
    return r;
  }

  function getSystemPrompt() {
    return currentRole === "electrician"
      ? SYSTEM_PROMPT_ELECTRICIAN
      : SYSTEM_PROMPT_CUSTOMER;
  }

  function getQuickReplies(userMsg) {
    const msg = (userMsg || "").toLowerCase();
    const map =
      currentRole === "electrician" ? QUICK_REPLIES_ELECTRICIAN : QUICK_REPLIES_CUSTOMER;

    if (currentRole === "electrician") {
      if (msg.includes("score") || msg.includes("el score") || msg.includes("rating")) return map.score;
      if (msg.includes("slot") || msg.includes("schedule")) return map.slot;
      if (msg.includes("order") || msg.includes("accept") || msg.includes("complete")) return map.order;
      if (msg.includes("commission") || msg.includes("block")) return map.commission;
      if (msg.includes("earn") || msg.includes("money") || msg.includes("payment")) return map.earning;
      if (msg.includes("dispute") || msg.includes("complaint") || msg.includes("customer")) return map.dispute;
    } else {
      if (msg.includes("ac") || msg.includes("cool") || msg.includes("air condition")) return map.ac;
      if (msg.includes("fan")) return map.fan;
      if (msg.includes("emergency") || msg.includes("spark") || msg.includes("burn") || msg.includes("trip") || msg.includes("shock")) return map.emergency;
      if (msg.includes("price") || msg.includes("cost") || msg.includes("₹") || msg.includes("charge")) return map.price;
      if (msg.includes("book") || msg.includes("schedule") || msg.includes("appoint")) return map.book;
      if (msg.includes("warranty") || msg.includes("refund") || msg.includes("guarantee")) return map.warranty;
      if (msg.includes("wiring") || msg.includes("wire") || msg.includes("circuit") || msg.includes("mcb")) return map.wiring;
      if (msg.includes("geyser") || msg.includes("water heater")) return map.geyser;
    }
    return map.default;
  }

  // ── Format bot message text ───────────────────────────────────────────────
  function formatMessage(text) {
    return text
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/(₹[\d,]+(?:–₹[\d,]+)?)/g, '<span class="ec-price">$1</span>')
      .replace(/^[-•]\s+(.+)/gm, "<li>$1</li>")
      .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
      .replace(/\n/g, "<br>");
  }

  // ── DOM Helpers ───────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  function scrollToBottom() {
    const el = $("ec-messages");
    if (el) el.scrollTop = el.scrollHeight;
  }

  function appendMessage(role, html, isHtml = true) {
    const el = $("ec-messages");
    if (!el) return;
    const wrap = document.createElement("div");
    wrap.className = `ec-msg ${role === "user" ? "ec-msg--user" : "ec-msg--bot"}`;
    const bubble = document.createElement("div");
    bubble.className = "ec-bubble";
    if (isHtml) bubble.innerHTML = html;
    else bubble.textContent = html;
    wrap.appendChild(bubble);
    el.appendChild(wrap);
    scrollToBottom();
  }

  function showTyping() {
    const el = $("ec-messages");
    if (!el) return;
    const wrap = document.createElement("div");
    wrap.className = "ec-msg ec-msg--bot";
    wrap.id = "ec-typing";
    wrap.innerHTML = `<div class="ec-bubble ec-typing"><span></span><span></span><span></span></div>`;
    el.appendChild(wrap);
    scrollToBottom();
  }

  function hideTyping() {
    const t = $("ec-typing");
    if (t) t.remove();
  }

  function renderQuickReplies(replies) {
    const el = $("ec-quick");
    if (!el) return;
    el.innerHTML = "";
    (replies || []).forEach((r) => {
      const btn = document.createElement("button");
      btn.className = "ec-quick-btn";
      btn.textContent = r;
      btn.onclick = () => sendMessage(r);
      el.appendChild(btn);
    });
  }

  // ── Load API key from server ───────────────────────────────────────────────
  // ── Load API key from server ───────────────────────────────────────────────
  async function loadKeyFromServer() {
    try {
      const res = await fetch("/api/chatbot/config");
      const data = await res.json();
      if (data.gemini_key) geminiKey = data.gemini_key;
      if (data.groq_key) window.groqKey = data.groq_key;
    } catch (e) {
      console.warn("Could not load chatbot config:", e);
    }
  }

  // ── AI API Call (Groq or Gemini) ──────────────────────────────────────────
  async function callAI(userText) {
    if (!geminiKey && !window.groqKey) {
      return "⚠️ AI assistant is not configured. Please add GROQ_API_KEY or GEMINI_API_KEY to your server .env file.";
    }

    // 1. Prioritize Groq (Llama-3-8b-8192) if key exists (OpenAI format)
    if (window.groqKey) {
      const groqUrl = "https://api.groq.com/openai/v1/chat/completions";
      
      // Convert Gemini message format to OpenAI format
      const openaiMessages = [
        { role: "system", content: getSystemPrompt() },
        ...messages.map(m => ({
          role: m.role === "model" ? "assistant" : "user",
          content: m.parts[0].text
        }))
      ];

      try {
        const res = await fetch(groqUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${window.groqKey}`
          },
          body: JSON.stringify({
            model: "llama-3.1-8b-instant",
            messages: openaiMessages,
            temperature: 0.7,
            max_tokens: 1024
          }),
        });

        if (res.status === 429) {
          return "⚠️ Groq rate limit reached. Please wait a moment.";
        }

        const data = await res.json();
        if (!res.ok) {
          return "❌ Groq request failed. Error: " + (data.error?.message || res.statusText);
        }
        return data.choices?.[0]?.message?.content || "⚠️ No response from Groq AI.";
      } catch (e) {
        console.warn("Groq error:", e);
        return "⚠️ Network error connecting to Groq. Please try again.";
      }
    }

    // 2. Fallback to Gemini if no Groq Key
    const MODELS = [
      "gemini-2.5-flash",
      "gemini-2.0-flash",
      "gemini-2.0-flash-lite",
      "gemini-1.5-flash-latest",
    ];

    const body = {
      system_instruction: { parts: [{ text: getSystemPrompt() }] },
      contents: messages,
    };

    for (const model of MODELS) {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${geminiKey}`;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (res.status === 429) {
          console.warn(`Rate limited by Google Cloud on ${model}.`);
          return "⚠️ Google AI rate limit reached. Please wait 1 full minute before messaging again.";
        }

        const data = await res.json();

        if (!res.ok) {
          if (res.status === 400 || res.status === 403) {
            return "❌ Gemini API key is invalid. Please check GEMINI_API_KEY in your server .env file.";
          }
          continue;
        }

        return data?.candidates?.[0]?.content?.parts?.[0]?.text || "⚠️ No response from AI.";
      } catch (e) {
        continue;
      }
    }

    return "⚠️ AI is temporarily unavailable. Please try again later.";
  }


  // ── Send Message ──────────────────────────────────────────────────────────
  async function sendMessage(text) {
    const input = $("ec-input");
    const msg = (text || (input ? input.value : "")).trim();
    if (!msg) return;
    if (input) { input.value = ""; input.style.height = "auto"; }

    // Add to history
    messages.push({ role: "user", parts: [{ text: msg }] });
    appendMessage("user", msg, false);
    renderQuickReplies([]);

    showTyping();
    const reply = await callAI(msg);
    hideTyping();

    if (reply) {
      messages.push({ role: "model", parts: [{ text: reply }] });
      appendMessage("bot", formatMessage(reply));
      renderQuickReplies(getQuickReplies(msg));
    }
  }

  // ── Clear Chat ────────────────────────────────────────────────────────────
  function clearChat() {
    messages = [];
    const el = $("ec-messages");
    if (el) el.innerHTML = "";
    renderQuickReplies([]);
    showWelcome();
  }

  // (API key is loaded from server — no setup screen needed)

  // ── Welcome Message ───────────────────────────────────────────────────────
  function showWelcome() {

    const role = detectRole();
    let welcome = "";

    if (role === "electrician") {
      welcome = `👷 Hi! I'm your <strong>Elecsure Electrician Assistant</strong>.<br><br>
I can help you with:<br>
• <strong>EL Score</strong> — how it's calculated & how to improve it<br>
• <strong>Slot management</strong> — creating, managing, missing slots<br>
• <strong>Order workflow</strong> — accepting, completing, disputes<br>
• <strong>Commission & earnings</strong> — payments, restrictions<br><br>
What do you need help with?`;
    } else if (role === "customer") {
      welcome = `⚡ Hi! I'm your <strong>Elecsure Customer Assistant</strong>.<br><br>
I can help you with:<br>
• <strong>All 29 services</strong> — pricing, duration, booking<br>
• <strong>Booking help</strong> — how to book, cancel, reschedule<br>
• <strong>Troubleshooting</strong> — appliance issues, wiring, safety<br>
• <strong>Emergency support</strong> — sparks, circuit trips, power loss<br><br>
What electrical issue can I help you with today?`;
    } else {
      welcome = `⚡ Hi! I'm the <strong>Elecsure Assistant</strong>.<br><br>
Ask me about our electrical services, pricing, how to book, or any home electrical issue in Karimnagar!`;
    }

    appendMessage("bot", welcome);
    renderQuickReplies(getQuickReplies(""));
  }

  // ── Toggle Chat Window ────────────────────────────────────────────────────
  function toggleChat() {
    const widget = $("ec-widget");
    if (!widget) return;

    isOpen = !isOpen;
    if (isOpen) {
      widget.classList.add("ec-widget--open");
      // Refresh role on each open
      detectRole();
      updateHeader();
      if (messages.length === 0) showWelcome();
      setTimeout(() => { const inp = $("ec-input"); if (inp) inp.focus(); }, 300);
    } else {
      widget.classList.remove("ec-widget--open");
    }
  }

  function updateHeader() {
    const label = $("ec-role-label");
    const statusText = $("ec-status-text");
    if (!label) return;
    if (currentRole === "electrician") {
      label.textContent = "Elecsure Assistant";
      if (statusText) statusText.textContent = "Electrician support · Online";
    } else if (currentRole === "customer") {
      label.textContent = "Elecsure Assistant";
      if (statusText) statusText.textContent = "Customer support · Online";
    } else {
      label.textContent = "Elecsure Assistant";
      if (statusText) statusText.textContent = "Online — replies instantly";
    }
  }

  // ── Inject CSS ────────────────────────────────────────────────────────────
  function injectStyles() {
    if ($("ec-styles")) return;
    const style = document.createElement("style");
    style.id = "ec-styles";
    style.textContent = `
/* ── Chatbot Widget ──────────────────────────────── */
#ec-fab {
  position: fixed;
  bottom: 28px;
  right: 28px;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #06b6d4);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  box-shadow: 0 8px 28px rgba(124,58,237,0.45);
  transition: transform 0.2s, box-shadow 0.2s;
  z-index: 9998;
}
#ec-fab:hover { transform: scale(1.12); box-shadow: 0 12px 36px rgba(124,58,237,0.55); }
#ec-fab .ec-pulse {
  position: absolute;
  top: 5px; right: 5px;
  width: 12px; height: 12px;
  background: #22c55e;
  border-radius: 50%;
  animation: ec-pulse 1.8s infinite;
  border: 2px solid #12121A;
}
@keyframes ec-pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.6); }
  50%      { box-shadow: 0 0 0 7px rgba(34,197,94,0); }
}

#ec-widget {
  position: fixed;
  bottom: 100px;
  right: 28px;
  width: 380px;
  max-height: 0;
  overflow: hidden;
  background: #12121A;
  border-radius: 20px;
  box-shadow: 0 24px 64px rgba(0,0,0,0.6);
  display: flex;
  flex-direction: column;
  z-index: 9999;
  border: 1px solid rgba(255,255,255,0.08);
  transition: max-height 0.35s cubic-bezier(0.4,0,0.2,1),
              opacity 0.3s ease,
              transform 0.35s cubic-bezier(0.4,0,0.2,1);
  opacity: 0;
  transform: translateY(16px) scale(0.97);
}
#ec-widget.ec-widget--open {
  max-height: 620px;
  opacity: 1;
  transform: translateY(0) scale(1);
}

/* Header */
.ec-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  background: linear-gradient(135deg, #1e1030, #0f2040);
  border-radius: 20px 20px 0 0;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  flex-shrink: 0;
}
.ec-avatar {
  width: 40px; height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #7c3aed, #06b6d4);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.ec-header-info { flex: 1; min-width: 0; }
.ec-header-name { font-size: 14px; font-weight: 700; color: #f1f5f9; }
.ec-status { display: flex; align-items: center; gap: 5px; margin-top: 2px; }
.ec-status-dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; flex-shrink: 0; }
.ec-status-text { font-size: 11px; color: #94a3b8; }
.ec-header-actions { display: flex; gap: 6px; }
.ec-hbtn {
  background: rgba(255,255,255,0.08);
  border: none;
  color: #94a3b8;
  border-radius: 8px;
  width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}
.ec-hbtn:hover { background: rgba(255,255,255,0.15); color: #f1f5f9; }

/* Messages */
#ec-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.1) transparent;
}
#ec-messages::-webkit-scrollbar { width: 4px; }
#ec-messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }

.ec-msg { display: flex; max-width: 88%; }
.ec-msg--bot { align-self: flex-start; }
.ec-msg--user { align-self: flex-end; flex-direction: row-reverse; }
.ec-bubble {
  padding: 10px 14px;
  border-radius: 16px;
  font-size: 13.5px;
  line-height: 1.55;
}
.ec-msg--bot .ec-bubble {
  background: rgba(255,255,255,0.07);
  color: #e2e8f0;
  border-radius: 4px 16px 16px 16px;
}
.ec-msg--user .ec-bubble {
  background: linear-gradient(135deg, #7c3aed, #5b21b6);
  color: #fff;
  border-radius: 16px 4px 16px 16px;
}
.ec-bubble strong { color: #f1f5f9; }
.ec-bubble ul { margin: 6px 0 0 0; padding-left: 18px; }
.ec-bubble li { margin-bottom: 2px; }
.ec-price {
  background: linear-gradient(135deg, #065f46, #064e3b);
  color: #6ee7b7;
  padding: 1px 6px;
  border-radius: 5px;
  font-weight: 700;
  font-size: 12px;
  white-space: nowrap;
}

/* Typing */
.ec-typing { display: flex; align-items: center; gap: 5px; padding: 12px 16px !important; }
.ec-typing span {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #7c3aed;
  animation: ec-bounce 1.2s infinite;
}
.ec-typing span:nth-child(2) { animation-delay: 0.2s; }
.ec-typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes ec-bounce {
  0%,80%,100% { transform: translateY(0); opacity: 0.5; }
  40%          { transform: translateY(-7px); opacity: 1; }
}

/* Quick Replies */
#ec-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 16px;
  border-top: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}
.ec-quick-btn {
  background: rgba(124,58,237,0.15);
  border: 1px solid rgba(124,58,237,0.4);
  color: #c4b5fd;
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  white-space: nowrap;
}
.ec-quick-btn:hover {
  background: rgba(124,58,237,0.35);
  border-color: #7c3aed;
  color: #fff;
}

/* Input */
.ec-input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid rgba(255,255,255,0.07);
  background: rgba(255,255,255,0.03);
  border-radius: 0 0 20px 20px;
  flex-shrink: 0;
}
#ec-input {
  flex: 1;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  color: #f1f5f9;
  font-size: 13.5px;
  padding: 9px 13px;
  resize: none;
  overflow: hidden;
  min-height: 38px;
  max-height: 100px;
  font-family: inherit;
  line-height: 1.4;
  transition: border-color 0.15s;
}
#ec-input::placeholder { color: rgba(255,255,255,0.3); }
#ec-input:focus { outline: none; border-color: rgba(124,58,237,0.6); }
#ec-send {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, #7c3aed, #06b6d4);
  border: none;
  border-radius: 10px;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: opacity 0.15s, transform 0.15s;
  flex-shrink: 0;
}
#ec-send:hover { opacity: 0.9; transform: scale(1.05); }

/* API setup */
.ec-api-setup {
  text-align: center;
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.ec-api-icon { font-size: 48px; }
.ec-api-setup h3 { color: #f1f5f9; font-size: 16px; margin: 0; }
.ec-api-setup p { color: #94a3b8; font-size: 13px; margin: 0; }
.ec-api-input {
  width: 100%;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 10px;
  color: #f1f5f9;
  font-size: 13px;
  padding: 10px 14px;
  margin-top: 8px;
  font-family: monospace;
}
.ec-api-input::placeholder { color: rgba(255,255,255,0.3); }
.ec-api-input:focus { outline: none; border-color: #7c3aed; }
.ec-api-btn {
  width: 100%;
  padding: 11px;
  background: linear-gradient(135deg, #7c3aed, #06b6d4);
  border: none;
  border-radius: 10px;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  margin-top: 4px;
  transition: opacity 0.15s;
}
.ec-api-btn:hover { opacity: 0.9; }

/* Responsive */
@media (max-width: 430px) {
  #ec-widget { width: calc(100vw - 24px); right: 12px; border-radius: 16px; }
  #ec-fab { bottom: 20px; right: 16px; }
}
    `;
    document.head.appendChild(style);
  }

  // ── Build DOM ─────────────────────────────────────────────────────────────
  function buildWidget() {
    // Remove old chatbot elements from base.html if present
    const oldBubble = document.getElementById("chatBubble");
    const oldWidget = document.getElementById("chatWidget");
    if (oldBubble) oldBubble.style.display = "none";
    if (oldWidget) oldWidget.style.display = "none";

    if ($("ec-fab")) return; // Already built

    detectRole();

    // FAB button
    const fab = document.createElement("button");
    fab.id = "ec-fab";
    fab.setAttribute("aria-label", "Open Elecsure Assistant");
    fab.innerHTML = `<span>💬</span><span class="ec-pulse"></span>`;
    fab.onclick = toggleChat;
    document.body.appendChild(fab);

    // Widget
    const w = document.createElement("div");
    w.id = "ec-widget";
    w.innerHTML = `
      <div class="ec-header">
        <div class="ec-avatar">⚡</div>
        <div class="ec-header-info">
          <div class="ec-header-name" id="ec-role-label">Elecsure Assistant</div>
          <div class="ec-status">
            <span class="ec-status-dot"></span>
            <span class="ec-status-text" id="ec-status-text">Online — replies instantly</span>
          </div>
        </div>
        <div class="ec-header-actions">
          <button class="ec-hbtn" title="Clear chat" onclick="window.__echatbot.clearChat()">🗑</button>
          <button class="ec-hbtn" title="Close" onclick="window.__echatbot.toggleChat()">✕</button>
        </div>
      </div>
      <div id="ec-messages"></div>
      <div id="ec-quick"></div>
      <div class="ec-input-row">
        <textarea id="ec-input" rows="1" placeholder="Type a message…"></textarea>
        <button id="ec-send" title="Send">➤</button>
      </div>`;
    document.body.appendChild(w);

    // Wire up input events
    const inp = $("ec-input");
    if (inp) {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
      inp.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 100) + "px";
      });
    }

    const sendBtn = $("ec-send");
    if (sendBtn) sendBtn.onclick = () => sendMessage();
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.__echatbot = {
    toggleChat,
    clearChat,
    sendMessage,
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  async function init() {
    injectStyles();
    buildWidget();
    updateHeader();
    await loadKeyFromServer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
