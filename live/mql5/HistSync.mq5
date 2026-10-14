// HistSync - ask the terminal for the account's whole deal history
// (2026-10-14: terminals only knew the deals they had witnessed; Python's
// history_deals_get() never makes them fetch older ones, HistorySelect does).
// Keeps asking until the count stops growing: a terminal that already holds a
// few local deals must not stop at those (Valere had 2 and stopped there).
#property script_show_inputs false
void OnStart()
  {
   int last=-1, same=0;
   for(int i=0;i<20;i++)
     {
      HistorySelect(0,TimeCurrent()+86400);
      int n=HistoryDealsTotal();
      PrintFormat("HistSync try %d: deals=%d orders=%d",i,n,HistoryOrdersTotal());
      if(n>0 && n==last) same++; else same=0;
      last=n;
      if(i>=2 && same>=2) break;
      Sleep(3000);
     }
   PrintFormat("HistSync done deals=%d",last);
  }
