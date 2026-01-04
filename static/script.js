const form = document.getElementById('chat-form');
const input = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const question = input.value;
    addMessage(question, 'user-message');
    input.value = '';

    const response = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
    });

    const data = await response.json();
    addMessage(data.answer, 'bot-message');
});

function addMessage(text, className) {
    const div = document.createElement('div');
    div.textContent = text;
    div.className = 'message ' + className;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}
