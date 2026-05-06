window.addEventListener("load", async function () {
  if (!window.Clerk) return;

  try {
    await window.Clerk.load();

    const nav = document.querySelector("nav") || document.body;

    if (window.Clerk.user) {
      const email = window.Clerk.user.primaryEmailAddress?.emailAddress || "Account";

      const el = document.createElement("a");
      el.href = "/account";
      el.textContent = "Account";
      el.style.marginLeft = "12px";
      el.style.color = "#60a5fa";
      el.style.fontWeight = "600";

      nav.appendChild(el);
    } else {
      const el = document.createElement("a");
      el.href = "/sign-in";
      el.textContent = "Sign In";
      el.style.marginLeft = "12px";
      el.style.color = "#60a5fa";
      el.style.fontWeight = "600";

      nav.appendChild(el);
    }
  } catch (e) {
    console.log("user status error", e);
  }
});
