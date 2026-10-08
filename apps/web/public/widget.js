/*!
 * ResolveAI chat widget loader. Plain JS, no dependencies.
 * <script src="https://YOUR-RESOLVEAI-HOST/widget.js" data-key="PUBLIC_KEY" async></script>
 *
 * Renders a launcher button and an iframe (/widget/{key}) inside a closed shadow root, so no
 * styles leak in either direction. The iframe asks for the page's origin over postMessage;
 * the browser sets event.origin on our reply, so a page can't claim to be another site.
 */
(function () {
  "use strict";
  if (window.__resolveaiWidget) return;

  var script = document.currentScript;
  var key = script && script.getAttribute("data-key");
  if (!key) {
    console.warn("[ResolveAI] widget.js needs a data-key attribute.");
    return;
  }
  var appOrigin = new URL(script.src, location.href).origin;
  var frameUrl = appOrigin + "/widget/" + encodeURIComponent(key);
  var FROM_WIDGET = "resolveai-widget";
  var FROM_HOST = "resolveai-host";

  var CHAT_ICON =
    '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-4-.9L3 20l1.1-4.1A8.4 8.4 0 1 1 21 11.5z"/></svg>';
  var CLOSE_ICON =
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  var css =
    ":host{all:initial}" +
    "*{box-sizing:border-box}" +
    ".launcher{position:fixed;right:20px;bottom:20px;z-index:2147483646;width:56px;height:56px;border:0;border-radius:16px;" +
    "background:#7B6CFF;color:#0E0F12;cursor:pointer;display:flex;align-items:center;justify-content:center;" +
    "box-shadow:0 0 28px rgba(123,108,255,.45),0 8px 24px rgba(0,0,0,.35);transition:transform .16s cubic-bezier(.2,0,0,1),background-color .15s}" +
    ".launcher:hover{background:#8F82FF}.launcher:active{transform:scale(.94)}" +
    ".launcher:focus-visible{outline:2px solid #7B6CFF;outline-offset:3px}" +
    ".launcher .icon{display:flex;transition:transform .2s cubic-bezier(.2,0,0,1),opacity .2s}" +
    ".panel{position:fixed;right:20px;bottom:88px;z-index:2147483647;width:380px;height:min(640px,calc(100vh - 112px));" +
    "border:1px solid rgba(255,255,255,.14);border-radius:16px;overflow:hidden;background:#0E0F12;" +
    "box-shadow:0 24px 64px rgba(0,0,0,.45);opacity:0;transform:translateY(12px) scale(.98);transform-origin:bottom right;" +
    "pointer-events:none;visibility:hidden;transition:opacity .18s ease,transform .2s cubic-bezier(.2,0,0,1),visibility 0s linear .2s}" +
    ".panel.open{opacity:1;transform:none;pointer-events:auto;visibility:visible;transition:opacity .18s ease,transform .2s cubic-bezier(.2,0,0,1)}" +
    "iframe{display:block;width:100%;height:100%;border:0;background:#0E0F12;color-scheme:dark}" +
    "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;height:100dvh;border-radius:0;border:0}" +
    ".launcher.open{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.launcher,.launcher .icon,.panel,.panel.open{transition:none}}";

  var host = document.createElement("div");
  host.setAttribute("data-resolveai-widget", "");
  var root = host.attachShadow({ mode: "closed" });
  root.innerHTML =
    "<style>" + css + "</style>" +
    '<div class="panel" role="dialog" aria-label="Customer support chat" id="panel"></div>' +
    '<button class="launcher" type="button" aria-expanded="false" aria-controls="panel" aria-label="Open chat">' +
    '<span class="icon">' + CHAT_ICON + "</span></button>";

  var panel = root.querySelector(".panel");
  var launcher = root.querySelector(".launcher");
  var icon = root.querySelector(".icon");
  var frame = null;
  var isOpen = false;

  function send(type) {
    if (frame && frame.contentWindow) {
      frame.contentWindow.postMessage({ source: FROM_HOST, type: type }, appOrigin);
    }
  }

  function ensureFrame() {
    if (frame) return;
    frame = document.createElement("iframe");
    frame.src = frameUrl;
    frame.title = "Customer support chat";
    frame.setAttribute("allow", "clipboard-write");
    panel.appendChild(frame);
  }

  function setOpen(next) {
    if (next === isOpen) return;
    isOpen = next;
    if (isOpen) ensureFrame();
    panel.classList.toggle("open", isOpen);
    launcher.classList.toggle("open", isOpen);
    launcher.setAttribute("aria-expanded", String(isOpen));
    launcher.setAttribute("aria-label", isOpen ? "Close chat" : "Open chat");
    icon.innerHTML = isOpen ? CLOSE_ICON : CHAT_ICON;
    if (isOpen) {
      // Focus the frame from the page (allowed: this runs in the launcher's click), then the
      // widget moves focus to its input.
      frame.focus();
      send("open");
    } else {
      launcher.focus();
    }
  }

  launcher.addEventListener("click", function () {
    setOpen(!isOpen);
  });

  window.addEventListener("message", function (event) {
    if (!frame || event.source !== frame.contentWindow || event.origin !== appOrigin) return;
    var data = event.data;
    if (!data || data.source !== FROM_WIDGET) return;
    if (data.type === "ready") {
      send("init");
      if (isOpen) send("open");
    } else if (data.type === "close") {
      setOpen(false);
    }
  });

  function mount() {
    document.body.appendChild(host);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);

  window.__resolveaiWidget = {
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
    toggle: function () {
      setOpen(!isOpen);
    },
  };
})();
