// AstroVed.AI Chatbot Widget — Embed on any website
// Usage: <script src="https://srivishnuu.github.io/AstroVed-Chatbot/chatbot-widget.js"></script>
(function(){
  if(document.getElementById('astroved-widget'))return;
  const iframe=document.createElement('iframe');
  iframe.id='astroved-widget';
  iframe.src='https://srivishnuu.github.io/AstroVed-Chatbot/index.html';
  iframe.style.cssText=[
    'position:fixed','bottom:0','right:0',
    'width:420px','height:680px',
    'border:none','z-index:999999',
    'background:transparent',
    'pointer-events:all'
  ].join(';');
  iframe.allow='microphone'; // needed for voice input
  document.body.appendChild(iframe);
})();