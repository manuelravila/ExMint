// config.js
(function() {
    const environments = {
        dev: {
            frontEndUrl: 'https://dev.exmint.me:3000',
            backEndUrl: 'https://dev.exmint.me:5000',
            suffix: '-dev'
        },
        stag: {
            frontEndUrl: 'https://stg-addin.exmint.me',
            backEndUrl: 'https://stg-app.exmint.me',
            suffix: '-stg'
        },
        prod: {
            frontEndUrl: 'https://addin.exmint.me',
            backEndUrl: 'https://app.exmint.me',
            suffix: ''
        }
    };

    const hostname = window.location.hostname;
    let env = 'prod';

    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === 'dev.exmint.me') {
        env = 'dev';
    } else if (hostname === 'stg-addin.exmint.me') {
        env = 'stag';
    }

    window.appConfig = environments[env];
})();
