module.exports = function (config) {
  config.set({
    basePath: "",
    frameworks: ["jasmine"],
    plugins: [
      require("karma-jasmine"),
      require("karma-chrome-launcher"),
      require("karma-coverage"),
      require("@angular-devkit/build-angular/plugins/karma"),
    ],
    client: {
      clearContext: false,
    },
    files: ["src/test.ts"],
    preprocessors: {
      "src/test.ts": ["@angular-devkit/build-angular"],
    },
    reporters: ["progress", "coverage"],
    port: 9876,
    colors: true,
    logLevel: config.LOG_INFO,
    autoWatch: false,
    browsers: ["ChromeHeadless"],
    singleRun: true,
    restartOnFileChange: false,
  });
};
