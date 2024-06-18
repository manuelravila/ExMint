// config.js
(function() {
    const devUrl = 'http://127.0.0.1:5000';
    const prodUrl = 'https://app.exmint.me';
    const stagingUrl = 'https://stg-app.exmint.me'; // This must be the app's URL 
    const hostname = window.location.hostname;

    let baseUrl;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        baseUrl = devUrl;
    } else if (hostname === 'stg-addin.exmint.me') { // This must be the add-in's URL 
        baseUrl = stagingUrl;
    } else {
        baseUrl = prodUrl;
    }

    window.appConfig = {
        apiUrl: baseUrl,
    };
})();
