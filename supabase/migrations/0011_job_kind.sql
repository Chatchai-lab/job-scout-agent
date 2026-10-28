-- Initiative applications: postings like 'Initiativbewerbung' and companies the user adds by hand.
alter table jobs add column kind text not null default 'posting'
    check (kind in ('posting', 'initiative'));
