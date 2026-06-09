window.addEventListener("load", async function () {
  if (!window.Clerk) return;

  try {
    await window.Clerk.load();

    const createBtn = document.querySelector('a[href="/sign-up"]');
    const signInBtn = document.querySelector('a[href="/sign-in"]');

    // Remove any duplicate dynamic auth links first
    document.querySelectorAll(".er-auth-link").forEach(el => el.remove());

    const nav = document.querySelector(".auth-actions") || document.querySelector("nav") || document.body;

    if (window.Clerk.user) {
      if (createBtn) createBtn.style.display = "none";
      if (signInBtn) signInBtn.style.display = "none";

      const account = document.createElement("a");
      account.href = "/account";
      account.textContent = "Account";
      account.className = "cta-btn secondary er-auth-link account-link";

      const logout = document.createElement("a");
      logout.href = "#";
      logout.textContent = "Logout";
      logout.className = "cta-btn secondary er-auth-link logout-link";
      logout.onclick = async function (e) {
        e.preventDefault();
        await window.Clerk.signOut();
        window.location.href = "/";
      };

      nav.appendChild(account);
      nav.appendChild(logout);
    } else {
      if (createBtn) createBtn.style.display = "";
      if (signInBtn) signInBtn.style.display = "";
    }
  } catch (e) {
    console.log("auth nav error", e);
  }
});
