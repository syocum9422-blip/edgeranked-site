window.addEventListener("load", async function () {
  if (!window.Clerk) return;

  try {
    await window.Clerk.load();

    if (window.Clerk.user) {
      const nav = document.querySelector("nav") || document.body;

      const logoutBtn = document.createElement("a");
      logoutBtn.href = "#";
      logoutBtn.textContent = "Logout";
      logoutBtn.style.marginLeft = "12px";
      logoutBtn.style.color = "#f87171";
      logoutBtn.style.fontWeight = "600";

      logoutBtn.onclick = async function (e) {
        e.preventDefault();
        await window.Clerk.signOut();
        window.location.reload();
      };

      nav.appendChild(logoutBtn);
    }
  } catch (e) {
    console.log("logout error", e);
  }
});
