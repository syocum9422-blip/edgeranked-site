window.addEventListener("load", async function () {
  if (!window.Clerk) return;

  try {
    await window.Clerk.load();

    const createBtn = document.querySelector('a[href="/sign-up"]');
    const signInBtn = document.querySelector('a[href="/sign-in"]');
    const accountLink = document.querySelector('a[href="/account"]');

    if (window.Clerk.user) {
      // Logged in
      if (createBtn) createBtn.style.display = "none";
      if (signInBtn) signInBtn.style.display = "none";

      if (!accountLink) {
        const nav = document.querySelector("nav") || document.body;

        const el = document.createElement("a");
        el.href = "/account";
        el.textContent = "Account";
        el.style.marginLeft = "12px";
        el.style.color = "#60a5fa";
        el.style.fontWeight = "600";

        nav.appendChild(el);
      }
    }
  } catch (e) {
    console.log("nav auth error", e);
  }
});
