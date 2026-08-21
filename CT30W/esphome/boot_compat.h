#pragma once

#include <cont.h>
#include <ets_sys.h>
#include <umm_malloc/umm_malloc.h>

extern "C" void call_user_start(void);

static cont_t ct30w_boot_cont __attribute__((aligned(16)));

extern "C" void app_entry_redefinable(void) {
  ets_uart_printf("\nCT30_BOOT:A\n");
  g_pcont = &ct30w_boot_cont;
  ets_uart_printf("CT30_BOOT:B\n");
  umm_init();
  ets_uart_printf("CT30_BOOT:C\n");
  call_user_start();
}

extern "C" void disable_extra4k_at_link_time(void) {}
