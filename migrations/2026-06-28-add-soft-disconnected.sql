-- Migration: Add soft_disconnected column to credential table
-- Allows soft-disconnecting (pausing) an institution while keeping accounts visible

ALTER TABLE credential ADD COLUMN soft_disconnected TINYINT(1) NOT NULL DEFAULT 0;
