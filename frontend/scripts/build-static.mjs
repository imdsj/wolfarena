import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { compileScript, compileTemplate, parse } from "@vue/compiler-sfc";
import ts from "typescript";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const sourceDirectory = path.join(frontendDirectory, "src");
const outputDirectory = path.join(frontendDirectory, "dist");

async function readSource(relativePath) {
  return readFile(path.join(sourceDirectory, relativePath), "utf8");
}

function transpileTypescript(source, fileName) {
  const result = ts.transpileModule(source, {
    fileName,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      verbatimModuleSyntax: false,
      isolatedModules: true,
    },
  });
  return result.outputText;
}

function rewriteModulePaths(source) {
  return source
    .replace(
      /(["'])(\.{0,2}\/[^"']+)\.vue\1/g,
      (_match, quote, modulePath) => `${quote}${modulePath}.js${quote}`,
    )
    .replace(
      /(["'])(\.{0,2}\/[^"']+)\.ts\1/g,
      (_match, quote, modulePath) => `${quote}${modulePath}.js${quote}`,
    );
}

async function compileVueComponent(relativePath) {
  const fileName = relativePath.split(path.sep).join("/");
  const source = await readSource(relativePath);
  const { descriptor, errors } = parse(source, { filename: fileName });
  if (errors.length) {
    throw new Error(`${fileName} 解析失败：${errors.join("; ")}`);
  }

  const id = `data-v-${Buffer.from(fileName).toString("hex").slice(0, 8)}`;
  const script = compileScript(descriptor, {
    id,
    genDefaultAs: "_sfc_main",
  });
  let scriptCode = transpileTypescript(script.content, `${fileName}.ts`);

  let renderCode = "";
  if (descriptor.template) {
    const template = compileTemplate({
      source: descriptor.template.content,
      filename: fileName,
      id,
      compilerOptions: {
        bindingMetadata: script.bindings,
      },
    });
    if (template.errors.length) {
      throw new Error(`${fileName} 模板失败：${template.errors.join("; ")}`);
    }
    renderCode = template.code.replace(
      "export function render",
      "function _sfc_render",
    );
  }

  const output = [
    rewriteModulePaths(scriptCode),
    renderCode,
    'if (typeof _sfc_main === "object") {',
    '  _sfc_main.render = typeof _sfc_render === "function" ? _sfc_render : undefined;',
    `  _sfc_main.__file = ${JSON.stringify(fileName)};`,
    "}",
    "export default _sfc_main;",
  ].join("\n");

  const target = path.join(
    outputDirectory,
    "src",
    relativePath.replace(/\.vue$/, ".js"),
  );
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, output, "utf8");
}

async function compileTypescriptModule(relativePath, { dropCss = false } = {}) {
  let source = await readSource(relativePath);
  if (dropCss) {
    source = source.replace(/^import\s+["'][^"']+\.css["'];?\s*$/gm, "");
  }
  const output = rewriteModulePaths(
    transpileTypescript(source, relativePath),
  );
  const target = path.join(
    outputDirectory,
    "src",
    relativePath.replace(/\.ts$/, ".js"),
  );
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, output, "utf8");
}

async function copyFile(source, target) {
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, await readFile(source));
}

await rm(outputDirectory, { recursive: true, force: true });
await mkdir(outputDirectory, { recursive: true });

await compileTypescriptModule("main.ts", { dropCss: true });
await compileVueComponent("App.vue");
await compileVueComponent(path.join("components", "ActionForm.vue"));
await compileVueComponent(path.join("components", "ConnectionStatus.vue"));
await compileVueComponent(path.join("components", "LobbyPanel.vue"));
await compileVueComponent(path.join("components", "RoomPanel.vue"));
await copyFile(
  path.join(sourceDirectory, "styles.css"),
  path.join(outputDirectory, "src", "styles.css"),
);
await copyFile(
  path.join(
    frontendDirectory,
    "node_modules",
    "vue",
    "dist",
    "vue.esm-browser.prod.js",
  ),
  path.join(outputDirectory, "vendor", "vue.esm-browser.prod.js"),
);

await writeFile(
  path.join(outputDirectory, "index.html"),
  `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="WolfArena 九人局最小联机入口" />
    <title>WolfArena 狼域</title>
    <link rel="stylesheet" href="/src/styles.css" />
    <script type="importmap">
      {
        "imports": {
          "vue": "/vendor/vue.esm-browser.prod.js"
        }
      }
    </script>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
`,
  "utf8",
);

console.log(`Static Vue build written to ${outputDirectory}`);
