# Use an official Node.js runtime as a parent image
FROM node:18

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Upgrade npm to the latest version
RUN npm install -g npm@latest

# Upgrade @azure/msal-node package to the latest version
RUN npm install @azure/msal-node@latest

# Install dependencies, including devDependencies
RUN npm install

# Run npm audit fix to address vulnerabilities automatically
RUN npm audit fix || echo "Continuing build process even if npm audit fix fails"

# Install webpack and webpack-cli globally to ensure they are available in the PATH
RUN npm install -g webpack webpack-cli

# Build the application (this will generate the files in the dist folder)
RUN npm run build

# Serve the application from the dist directory
WORKDIR /app/dist

# Use a simple static file server like 'serve'
RUN npm install -g serve

# Start the application by serving the dist directory
CMD ["serve", "-s", "."]
