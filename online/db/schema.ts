// Intentionally empty by default.
// Add Drizzle tables here when the site actually needs a database.
// See examples/d1/db/schema.ts for an opt-in example.
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const sessions = sqliteTable('car_sessions', {
  id: text('id').primaryKey(), owner: text('owner').notNull(), title: text('title').notNull(),
  payload: text('payload').notNull(), version: integer('version').notNull().default(0),
  busy: integer('busy').notNull().default(0), updated: integer('updated').notNull(),
});
export const quota = sqliteTable('car_quota', { id: text('id').primaryKey(), count: integer('count').notNull().default(0) });
