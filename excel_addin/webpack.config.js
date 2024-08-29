const devCerts = require("office-addin-dev-certs");
const CopyWebpackPlugin = require("copy-webpack-plugin");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const path = require('path');
const fs = require('fs');
const webpack = require('webpack');

// Function to get the HTTPS options for local development
async function getHttpsOptions() {
  const certPath = path.resolve(__dirname, '../dev_exmint_me.crt');
  const keyPath = path.resolve(__dirname, '../dev_exmint_me.key');

  if (fs.existsSync(certPath) && fs.existsSync(keyPath)) {
    return {
      key: fs.readFileSync(keyPath),
      cert: fs.readFileSync(certPath)
    };
  } else {
    // Fallback to dev certificates if the specified ones are not found
    const httpsOptions = await devCerts.getHttpsServerOptions();
    return { ca: httpsOptions.ca, key: httpsOptions.key, cert: httpsOptions.cert };
  }
}

module.exports = async (env, options) => {
  const dev = options.mode === "development"; // CHANGE THIS FOR PRODUCTION to 'production'

  const config = {
    devtool: false,
    entry: {
      polyfill: ["core-js/stable", "regenerator-runtime/runtime"],
      taskpane: ["./src/taskpane/taskpane.js", "./src/taskpane/taskpane.html", "./src/taskpane/taskpane.css", "./src/taskpane/config.js"],
      dashboard: ["./src/taskpane/dashboard.js", "./src/taskpane/dashboard.html", "./src/taskpane/taskpane.css", "./src/taskpane/config.js"],
      commands: "./src/commands/commands.js",
    },
    output: {
      clean: true,
      path: path.resolve(__dirname, 'dist'),
      filename: '[name].[contenthash].bundle.js',
    },
    resolve: {
      extensions: [".html", ".js"],
    },
    module: {
      rules: [
        {
          test: /\.js$/,
          exclude: /node_modules/,
          use: {
            loader: "babel-loader",
            options: {
              presets: ["@babel/preset-env"],
            },
          },
        },
        {
          test: /\.html$/,
          exclude: /node_modules/,
          use: "html-loader",
        },
        {
          test: /\.(png|jpg|jpeg|gif|ico)$/,
          type: "asset/resource",
          generator: {
            filename: "assets/[name][ext][query]",
          },
        },
        {
          test: /\.css$/i,
          include: path.resolve(__dirname, "src"),
          use: ["style-loader", "css-loader"],
        },
      ],
    },
    plugins: [
      new HtmlWebpackPlugin({
        filename: "taskpane.html",
        template: "./src/taskpane/taskpane.html",
        chunks: ["polyfill", "taskpane"],
      }),
      new HtmlWebpackPlugin({
        template: './src/taskpane/dashboard.html',
        filename: 'dashboard.html',
        chunks: ['dashboard'],
      }),
      new CopyWebpackPlugin({
        patterns: [
          {
            from: "assets/*",
            to: "assets/[name][ext][query]",
          },
          {
            from: "manifest*.xml",
            to: "[name]" + "[ext]",
            transform(content) {
              return content.toString().replace(/https:\/\/localhost:3000\//g, 'https://dev.exmint.me:3000/');
            },
          },
        ],
      }),
      new HtmlWebpackPlugin({
        filename: "commands.html",
        template: "./src/commands/commands.html",
        chunks: ["polyfill", "commands"],
      }),
      new webpack.DefinePlugin({
        'process.env.NODE_ENV': JSON.stringify(options.mode),
      }),
    ],
    devServer: {
      allowedHosts: [
        '127.0.0.1',
        'localhost',
        'dev.exmint.me',
        'stg.exmint.me',
        'prod.exmint.me'
      ],
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store"
      },
      server: {
        type: "https",
        options: env.WEBPACK_BUILD || options.https !== undefined ? options.https : await getHttpsOptions(),
      },
      port: process.env.npm_package_config_dev_server_port || 3000,
    },
  };

  return config;
};
