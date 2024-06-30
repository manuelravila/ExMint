// config.js
(function() {
    const devUrl = 'https://dev.exmint.me:5000';
    const prodUrl = 'https://app.exmint.me';
    const stagingUrl = 'https://stg-app.exmint.me'; 
    const devSuffix = '-dev';
    const prodSuffix = '';
    const stagSuffix = '-stg'; 
    const hostname = window.location.hostname;

    let baseUrl;
    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === 'dev.exmint.me') {
        baseUrl = devUrl;
        suffix = devSuffix;
    } else if (hostname === 'stg-addin.exmint.me') { // This must be the add-in's URL 
        baseUrl = stagingUrl;
        suffix = stagSuffix;
    } else {
        baseUrl = prodUrl;
        suffix = prodSuffix;
    }

    window.appConfig = {
        apiUrl: baseUrl,
        suffix: suffix,
    };
})();
