/* Local probe configuration for the read-only generic probe build.
 * Placeholder (zero) GUIDs: the generic probe boots from a USB stick, writes its
 * capture to that same USB (root), and pins neither an internal nor a Windows
 * partition. Never distribute this file. */
#pragma once
#define GU_INTERNAL_PARTITION_INITIALIZER {0x00000000,0x0000,0x0000,{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}}
#define GU_WINDOWS_PARTITION_INITIALIZER  {0x00000000,0x0000,0x0000,{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}}
