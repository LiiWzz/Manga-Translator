const status = document.getElementById("status");
document.getElementById("connect").addEventListener("click", () => {
  chrome.tabs.create({url: "http://127.0.0.1:8000/settings"});
});
async function check() {
  try {
    const response = await fetch("http://127.0.0.1:8000/api/v1/provider/status");
    if (!response.ok) throw new Error("HTTP " + response.status);
    const result = await response.json();
    status.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    status.textContent = "Backend offline or not accessible: " + error.message;
  }
}
document.getElementById("check").addEventListener("click", check);
check();
