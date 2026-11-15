import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const posts = defineCollection({
  loader: glob({ pattern: '*.json', base: './src/content/posts' }),
  schema: z.object({
    id: z.number().int(),
    date: z
      .string()
      .transform((value) => new Date(value))
      .refine((value) => !Number.isNaN(value.getTime()), {
        message: 'date must be a valid ISO 8601 string',
      }),
    text: z.string(),
    media_type: z.enum(['voice', 'video', 'photo', 'document', 'text']),
    duration_sec: z.number().int().nullable().optional(),
    views: z.number().int().nonnegative(),
    reactions: z.number().int().nonnegative(),
    telegram_link: z.string().url(),
    category: z.string().nullable(),
  }),
});

export const collections = { posts };
