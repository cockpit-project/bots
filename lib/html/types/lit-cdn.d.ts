declare module "https://cdn.jsdelivr.net/gh/lit/dist@3/all/lit-all.min.js" {
    type PropertyDeclaration = {
        type?: typeof String | typeof Number | typeof Boolean | typeof Array | typeof Object;
        state?: boolean;
    };

    export type CSSResult = { cssText: string };

    export class LitElement extends HTMLElement {
        static properties: Record<string, PropertyDeclaration>;
        static styles: CSSResult | CSSResult[];
        connectedCallback(): void;
        disconnectedCallback(): void;
        createRenderRoot(): HTMLElement | DocumentFragment;
        requestUpdate(): void;
        render(): unknown;
    }

    export function css(strings: TemplateStringsArray, ...values: unknown[]): CSSResult;
    export function html(strings: TemplateStringsArray, ...values: unknown[]): unknown;
    export const nothing: symbol;
    export function repeat<T>(
        items: Iterable<T>,
        keyFn: (item: T) => unknown,
        template: (item: T) => unknown,
    ): unknown;
}
