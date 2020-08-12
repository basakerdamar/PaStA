import matplotlib.pyplot as plt
import pandas as pd

from pypasta.LinuxMaintainers import LinuxMaintainers

from logging import getLogger


log = getLogger(__name__[-15:])

def offlist_evaluate(config, prog, argv):
    repo = config.repo

    all_maintainers = LinuxMaintainers(repo, revision=repo.tags[-1][0])

    def get_commit_object(upstream):
        return repo.get_commit(upstream)

    def get_author_name(commit):
        return commit.committer.name

    def get_commit_date(commit):
        return pd.to_datetime(commit.committer.date.date())
    
    def get_commit_files(commit):
        return commit.diff.affected
        
    def check_if_maintainer(line):
        filenames = line['files']
        maintainers = []
        for filename in filenames:
            sections = all_maintainers.get_sections_by_file(filename)
            sections -= {'THE REST'}
            for section in sections:
                _, mtrs, _ = all_maintainers.get_maintainers(section)
                maintainers += mtrs
        return line['author.name'].lower() in [x[0].lower() for x in maintainers]

    try:
        by_author = pd.read_csv('by_author')
    except FileNotFoundError:
        log.error('First run ./pasta offlist')
        quit()

    log.info('Re-structuring off-list data')

    by_author['upstream'] = by_author['upstream'].map(lambda x: x.split(','))
    by_author.set_index('Author', inplace=True)
    by_author = pd.melt(by_author['upstream'].apply(pd.Series).reset_index(), 
                id_vars=['Author'],
                value_name='upstream').sort_index()
    by_author.drop('variable', axis=1, inplace=True)
    offlist = by_author[['upstream']].dropna()


    df_repo = pd.DataFrame(config.upstream_hashes)
    df_repo.columns= ['upstream']

    log.info('  ↪ done.')
    log.info('Getting repository data')

    df_repo['commit_obj'] = df_repo['upstream'].map(get_commit_object)
    df_repo['date'] = df_repo['commit_obj'].map(get_commit_date)
    df_repo['author.name'] = df_repo['commit_obj'].map(get_author_name)
    df_repo['files'] = df_repo['commit_obj'].map(get_commit_files)
    df_repo.drop('commit_obj', inplace=True, axis=1)

<<<<<<< HEAD
    patch_denorm_upstream = \
        pd.read_csv('resources/linux/resources/patch_denorm_upstream.csv')
    offlist = patch_denorm_upstream[patch_denorm_upstream['patch_id']=='_']\
                                                                  [['upstream']]
    offlist.dropna(inplace=True)

    offlist = pd.merge(offlist, df_repo, on = 'commit', how='left')
=======
    offlist = pd.merge(offlist, df_repo, on = 'upstream', how='left')
        
    log.info('  ↪ done.')
    log.info('Checking maintainers')
>>>>>>> 10d8db3... bin/pasta_offlist_evaluate.py

    offlist['author_is_maintainer'] = offlist.apply(check_if_maintainer, axis=1)
    
    log.info('  ↪ done.')
    log.info('Generating plots')

    ax = offlist.groupby('author.name')['author_is_maintainer']\
            .value_counts()\
            .sort_values(ascending=False)[:20]\
            .unstack()\
            .plot.barh(stacked=True, color=['r','g'])

    ax.figure.savefig('top_off-list_authors.pdf', bbox_inches = "tight")

    repo_authors = df_repo.groupby('author.name')\
                            .size()\
                            .reset_index()
    offlist_authors = offlist.groupby(['author.name'])\
                            .size()\
                            .reset_index()
                                
    authors = pd.merge(repo_authors, offlist_authors, 
                            on='author.name', 
                            how='left')\
                            .fillna(0)
    authors['offlist (%)'] = \
                        authors.apply(lambda x: 100*x['0_y']/(x['0_x']), axis=1)

    ax = authors.plot.scatter(x='0_x', y='offlist (%)', figsize=(15, 10))
    ax.set_xlabel('Total number of commits')
    
    ax.figure.savefig('total_vs_off-list_percentage.pdf', bbox_inches = "tight")


    ax = authors.plot.scatter(x='0_x', y='0_y', figsize=(15, 10), alpha=0.5)
    ax.set_xlabel('Total number of commits')
    ax.set_ylabel('Offlist commits')
    
    ax.figure.savefig('total_vs_off-list.pdf', bbox_inches = "tight")
