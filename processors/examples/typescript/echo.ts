#!/usr/bin/env node
/**
 * Echo processor - demonstrates the basic processor contract in TypeScript.
 *
 * Compile: npx tsc echo.ts --outDir dist --target ES2020 --module commonjs
 * Run:     node dist/echo.js
 * Or:      npx ts-node echo.ts
 *
 * Reads JSON Lines from stdin, writes results to stdout.
 * Each output must include id, chat_id, and status.
 */

import * as readline from 'readline';

// Input message from tele (see docs/contracts.md)
interface MessageInput {
    id: number;
    chat_id: number;
    text?: string | null;
    sender_id?: number | null;
    date?: string | null;
    is_forwarded?: boolean;
    forward_from_id?: number | null;
    has_media?: boolean;
    media_type?: string | null;
    reactions?: Array<{ emoji: string; count: number }>;
}

// Output result to tele (see docs/contracts.md)
interface MessageOutput {
    id: number;
    chat_id: number;
    status: 'success' | 'failed';
}

/**
 * Process a single message and return the result.
 */
function processMessage(msg: MessageInput): MessageOutput {
    // Validate required fields
    if (msg.id === undefined || msg.chat_id === undefined) {
        console.error('[ERROR] Missing id or chat_id');
        return { id: 0, chat_id: 0, status: 'failed' };
    }

    // Example: log the message text (for debugging)
    if (msg.text) {
        const preview = msg.text.length > 50 ? msg.text.slice(0, 50) + '...' : msg.text;
        console.error(`[INFO] Processing message ${msg.id}: ${preview}`);
    }

    // Your processing logic goes here
    // This example just marks everything as success
    return {
        id: msg.id,
        chat_id: msg.chat_id,
        status: 'success'
    };
}

/**
 * Main entry point - reads JSON Lines from stdin.
 */
async function main(): Promise<void> {
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
        terminal: false
    });

    for await (const line of rl) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        try {
            const msg: MessageInput = JSON.parse(trimmed);
            const result = processMessage(msg);
            console.log(JSON.stringify(result));
        } catch (e) {
            console.error(`[ERROR] Invalid JSON: ${e}`);
            console.log(JSON.stringify({ id: 0, chat_id: 0, status: 'failed' }));
        }
    }
}

main().catch((err) => {
    console.error('[ERROR]', err);
    process.exit(1);
});