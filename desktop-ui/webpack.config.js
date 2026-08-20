const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');

module.exports = (env) => {
  const target = env.target || 'renderer';

    const config = {
    mode: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    devtool: 'source-map',
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
    ],
  };
};
