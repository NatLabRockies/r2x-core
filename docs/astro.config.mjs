import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';

export default defineConfig({
  site: 'https://natlabrockies.github.io',
  base: '/r2x-core/',
  markdown: { processor: unified() },
  integrations: [
    mermaid({ enableLog: false }),
    starlight({
      title: 'r2x-core',
      description: 'Shared infrastructure for power-system model translators.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/NatLabRockies/r2x-core' }],
      editLink: { baseUrl: 'https://github.com/NatLabRockies/r2x-core/edit/main/' },
      customCss: ['./src/styles/api.css'],
      sidebar: [
        { label: 'Tutorials', items: [{ autogenerate: { directory: 'tutorials' } }] },
        { label: 'How-to guides', items: [{ label: 'Install', link: '/install/' }, { label: 'Task guides', items: [{ autogenerate: { directory: 'how-tos' } }] }] },
        { label: 'Reference/API', items: [{ autogenerate: { directory: 'references' } }] },
        { label: 'Explanation', items: [{ autogenerate: { directory: 'explanations' } }] },
        { label: 'Troubleshooting', items: [{ label: 'Diagnose failures', link: '/troubleshooting/' }] },
        { label: 'Changelog', items: [{ label: 'Releases and versions', link: '/release-history/' }, { label: 'Release notes', link: '/release-notes/' }] },
        { label: 'Contributors', items: [{ label: 'Development', link: '/contributing/' }] },
      ],
    }),
  ],
});
