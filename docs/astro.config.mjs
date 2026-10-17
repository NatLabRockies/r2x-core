import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';

export default defineConfig({
  site: 'https://natlabrockies.github.io',
  base: '/r2x-core/',
  markdown: { processor: unified() },
  integrations: [
    mermaid({ enableLog: false, mermaidConfig: { theme: "base", fontFamily: "system-ui, sans-serif" } }),
    starlight({
      title: 'r2x-core',
      routeMiddleware: './src/routeData.ts',
      logo: {
        light: './src/assets/r2x-logo-full-color.svg',
        dark: './src/assets/r2x-logo-white.svg',
        alt: 'R2X framework logo',
        replacesTitle: false,
      },
      description: 'Shared infrastructure for power-system model translators.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/NatLabRockies/r2x-core' }, { icon: 'code-branch', label: 'Browse source versions', href: 'https://github.com/NatLabRockies/r2x-core/tags' }],
      editLink: { baseUrl: 'https://github.com/NatLabRockies/r2x-core/edit/main/docs/' },
      customCss: ['./src/styles/brand.css', './src/styles/api.css'],
      sidebar: [
        { label: 'Getting started', items: [{ label: 'Installation', link: '/install/' }, { label: 'Prerequisites and environment', link: '/getting-started/environment/' }, { label: 'Verify installation and first use', link: '/getting-started/verify/' }] },
        { label: 'Tutorials', items: [{ autogenerate: { directory: 'tutorials' } }] },
        { label: 'How-to guides', items: [{ autogenerate: { directory: 'how-tos' } }] },
        { label: 'Reference/API', items: [{ autogenerate: { directory: 'references' } }] },
        { label: 'Explanation', items: [{ autogenerate: { directory: 'explanations' } }] },
        { label: 'Troubleshooting', items: [{ label: 'Diagnose failures', link: '/troubleshooting/' }] },
        { label: 'Changelog', link: '/release-notes/' },
        { label: 'Contributors', items: [{ label: 'Development', link: '/contributing/' }] },
      ],
    }),
  ],
});
