// config.js
(function() {
    const devUrl = 'http://127.0.0.1:5000/';
    const prodUrl = 'https://app.exmint.me/';
    const isDevelopment = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

    window.appConfig = {
        apiUrl: isDevelopment ? devUrl : prodUrl,
    };
})();
