// Stub for react-syntax-highlighter in Vitest.
// The real package's CJS build pulls in ESM-only refractor and blows up under
// jsdom. Tests don't render syntax highlighting, so a <pre>{children}</pre>
// is plenty. The same default export covers the package root, the deep
// language entry points, and the deep style entry points (we re-route the
// whole subtree via a single alias in vitest.config.ts).

import * as React from "react";

type AnyProps = Record<string, unknown> & { children?: React.ReactNode };

type StubComponent = React.FC<AnyProps> & {
  registerLanguage: (name: string, lang: unknown) => void;
};

const Stub = (({ children }: AnyProps) => (
  <pre data-stub="syntax-highlighter">{children as React.ReactNode}</pre>
)) as StubComponent;
Stub.registerLanguage = () => undefined;

export const Light = Stub;
export const Prism = Stub;
export default Stub;

// Default export for `.../languages/hljs/<lang>` imports — refractor expects
// a function/object; tests only pass it through registerLanguage which is a
// no-op stub.
export const __languageStub = () => undefined;

// Style modules (e.g. `.../styles/hljs/vs2015`) — return a plain object so
// `useSyntaxTheme` can pass it as a prop without crashing.
export const vs2015 = {};
export const github = {};
