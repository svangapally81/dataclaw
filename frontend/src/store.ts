import { configureStore } from "@reduxjs/toolkit";

import { dataclawApi } from "./services/api";

export const store = configureStore({
  reducer: {
    [dataclawApi.reducerPath]: dataclawApi.reducer,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(dataclawApi.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
