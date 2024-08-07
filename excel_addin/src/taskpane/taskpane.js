console.log("Taskpane script loaded");

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toaster';
  toast.textContent = message;

  document.body.appendChild(toast);
  setTimeout(() => document.body.removeChild(toast), 5000); // Change duration to 5 seconds
}

// Ensure Office is ready before running the script
Office.onReady(function (info) {
  if (info.host === Office.HostType.Excel) {
    document.addEventListener('DOMContentLoaded', function () {
      try {
        if (!window.appConfig || !window.appConfig.backEndUrl) {
          throw new Error('appConfig or backEndUrl is not defined');
        }

        const loginForm = document.querySelector('form');
        const serverAddress = window.appConfig.backEndUrl;

        loginForm.addEventListener('submit', function (e) {
          e.preventDefault(); // Prevent the default form submission

          const formData = new FormData(loginForm);
          const data = {};
          formData.forEach((value, key) => { data[key] = value; });

          fetch(`${serverAddress}/login`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Request-Source': 'Excel-Add-In'
            },
            body: JSON.stringify(data)
          })
          .then(response => {
            if (!response.ok) {
              throw new Error('Login Unsuccessful. Please check email and password');
            }
            return response.json();
          })
          .then(data => {
            localStorage.setItem('authToken', data.token);
            console.log('Login successful, token stored.');
            window.location.href = 'dashboard.html'; // Redirect on success
          })
          .catch((error) => {
            console.error('Error during fetch:', error);
            showToast('Login Unsuccessful. Please check email and password');
          });
        });

        // Dynamically set login form links
        var resetPasswordLink = document.getElementById('resetPasswordLink');
        if (resetPasswordLink) {
          resetPasswordLink.addEventListener('click', function (event) {
            event.preventDefault();
            var url = 'https://exmint.me/app' + window.appConfig.suffix + '/password-reset';
            console.log('Link clicked:', url);
            window.open(url, '_blank');
          });
        }

        var createAccountLink = document.getElementById('createAccountLink');
        if (createAccountLink) {
          createAccountLink.addEventListener('click', function (event) {
            event.preventDefault();
            var url = 'https://exmint.me/app' + window.appConfig.suffix + '/register';
            console.log('Link clicked:', url);
            window.open(url, '_blank');
          });
        }

      } catch (error) {
        console.error('Error during DOMContentLoaded:', error);
        showToast('Initialization error. Please try again.');
      }
    });
  }
});
