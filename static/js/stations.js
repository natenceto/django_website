document.addEventListener("DOMContentLoaded", function () {

  const tabLinks = document.querySelectorAll('#stationTabs a[data-toggle="tab"]');

  tabLinks.forEach(tab => {
    tab.addEventListener('shown.bs.tab', function (event) {
      const tabId = event.target.getAttribute('href').substring(1); // "add" или "list"
      const url = new URL(window.location);
      url.searchParams.set('tab', tabId);
      window.history.replaceState({}, '', url);
    });
  });
});