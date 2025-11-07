let subjectCount = 0;
function addSubject() {
    const div = document.createElement('div');
    div.innerHTML = `
        <input type="text" placeholder="Subject" class="w-full p-3 border rounded-lg">
        <input type="number" placeholder="Score" class="w-full p-3 border rounded-lg">
    `;
    document.getElementById('subjects').appendChild(div);
    subjectCount++;
}

document.getElementById('uploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    // Collect data efficiently
    const formData = { subjects: [] };
    // ... parse inputs
    const res = await fetch('/admin/upload', { method: 'POST', body: JSON.stringify(formData), headers: {'Content-Type': 'application/json'} });
    const json = await res.json();
    alert(json.status === 'success' ? 'Uploaded!' : json.error);
});