const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');

module.exports = (env) => {
  const target = env.target || 'renderer';

  const config = {
    mode: 'development',
    devtool: 'source-map',
    externalsPresets: { electronMain: true, electronPreload: true },
    // Bind BOTH the source specifier ('electron') and the preset's resolved
    // request ('electron/main') to Electron's real BUILT-IN module. Plain
    // require('electron') resolves to node_modules/electron/index.js, which
    // exports the executable PATH (a string), not the API.
    externals: {
      electron: 'commonjs2 electron/main',
      'electron/main': 'commonjs2 electron/main',
      'electron/common': 'commonjs2 electron',
      'electron/renderer': 'commonjs2 electron',
    },
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx'],
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: 'ts-loader',
          exclude: /node_modules/,
        },
        {
          test: /\.css$/,
          use: ['style-loader', 'css-loader'],
        },
      ],
    },
  };

  if (target === 'main') {
    return {
      ...config,
      target: 'electron-main',
      entry: './src/main/main.ts',
      output: {
        path: path.resolve(__dirname, 'dist/main'),
        filename: 'main.js',
      },
    };
  }

  if (target === 'preload') {
    return {
      ...config,
      target: 'electron-preload',
      entry: './src/main/preload.ts',
      output: {
        path: path.resolve(__dirname, 'dist/main'),
        filename: 'preload.js',
      },
    };
  }

  // renderer
  return {
    ...config,
    target: 'electron-renderer',
    entry: './src/renderer/index.tsx',
    output: {
      path: path.resolve(__dirname, 'dist/renderer'),
      filename: 'renderer.js',
    },
    plugins: [
      new HtmlWebpackPlugin({
        template: './src/renderer/index.html',
      }),
      // The startup screen Electron shows until the FastAPI backend is ready.
      // `inject: false` keeps the compiled renderer bundle out of it.
      new HtmlWebpackPlugin({
        template: './src/renderer/splash.html',
        filename: 'splash.html',
        inject: false,
        chunks: [],
        minify: false,
      }),
    ],
  };
};
