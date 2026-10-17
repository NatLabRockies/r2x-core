import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import apiContents from './generated/api-toc.json';

export const onRequest = defineRouteMiddleware((context) => {
  const route = context.locals.starlightRoute;
  const items = apiContents[route.id as keyof typeof apiContents]
    ?? apiContents[`${route.id}/index` as keyof typeof apiContents];
  if (items?.length && route.toc) {
    route.toc = { minHeadingLevel: 2, maxHeadingLevel: 6, items };
  }
});
