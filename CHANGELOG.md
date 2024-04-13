## [0.2.0] - 2024-03-26 
### Added
- Added Excel Add-In code.

### Changed
- Updated /sync API to include number of transactions and type of refresh
- Updated /sync API to record an audit entry with response from Plaid in every refresh

## [0.1.4] - 2024-04-02

### Added
- Excel Add-In code.

## [0.1.3] - 2024-04-01

### Added
- Integrated Bitwarden Secrets Manager (BWS) for secure management of sensitive configuration information, including database passwords, Plaid credentials, and mail server settings.
- Implemented `get_bw_secret` function in `config.py` to dynamically fetch secrets based on secret keys from BWS, enhancing security and configuration management.
- Established two BWS service accounts: one designated for production (`ExMint-Prod`) and another for development and staging (`ExMint-Dev`). This strategy ensures appropriate separation and access control for environment-specific secrets.
- Added documentation within `config.py` detailing the purpose and usage of each function, particularly emphasizing the secure retrieval of secrets from BWS and the rationale behind using separate service accounts for different environments.

### Changed
- Replaced hard-coded sensitive information in the application configuration with dynamically retrieved secrets from BWS. This change applies to the following configuration settings:
    - Database URIs across different environments (development, staging, production).
    - Secret keys and encryption keys used for security purposes.
    - Plaid API credentials, supporting both development and production usage with environment-appropriate access.
    - Mail server configurations, including server addresses, ports, and authentication credentials.

### Security
- Enhanced application security by removing hard-coded sensitive information from the codebase. All sensitive configurations are now securely stored and managed through BWS, minimizing potential exposure and risk.
- Implemented case-insensitive search within `get_bw_secret` function to robustly match secret keys, improving the reliability of secret retrieval across varied naming conventions.

### Fixed
- Addressed potential configuration management issues by introducing a more secure, scalable, and maintainable approach to handling sensitive information through the integration of BWS.


## [0.1.2] - 2024-03-26 
### Added
- Added automatic database switching based on Git branch.

## [0.1.1] - 2024-03-26 
### Added
- Added version information to the footer of the dashboard.
- Added 'version' key to the JSON response of the /sync API endpoint for better tracking and compatibility.

### Removed
- Removed 'Support' button from the dashboard header for a cleaner user interface.
- Removed 'Help and Support' right sidebar from the dashboard to streamline user experience.

### Changed
- Updated footer styling for better readability and alignment using Bootstrap classes.
- Made 'Automatos Consulting Inc.' a clickable link in the footer, linking to the official website.

## [0.1.0] - 2024-03-27
### Added
- Initial release of exMint.
- Support for user authentication and profile management.

### Fixed
- Corrected timezone discrepancies in log entries.

### Changed
- Updated Flask framework from 1.1.2 to 1.1.3 for improved security.
