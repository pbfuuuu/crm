// Подтверждение опасных действий: <form data-confirm="Удалить?">
document.addEventListener("submit", function (e) {
  var msg = e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) {
    e.preventDefault();
  }
});
