#! /usr/bin/env python

import os
import glob
import click
import numpy as np
import pandas as pd
from skbio import io


"""
Script for mapping genes to contigs, MAGS and eggNOG annotations
input files required:
1) clustering file: tab-delimited file with cluster ID and gene ID
2) Non-redundant gene catalogue (fasta)
3) Contig files (fasta)
4) binned contigs (MAGS)
5) taxonomy files (tsv)
6) EggNOG annotation file (tsv)
The script outputs a tsv file that links the non-redundant gene catalogue back to contigs, MAGs and to eggNOG annotations

"""
def load_fasta_ids(path):
  """
  Reads sequences from a fasta file and extracts identifiers.

    Parameters
    ----------
  input_file : str
        fasta file containing contigs and gene identifiers

    Returns
    -------
  List of fasta identifiers
  """
  fasta_ids = [seq.metadata['id'] for seq in io.read(path, format='fasta')]
  return fasta_ids

def load_mags_contigs_taxonomies_for_sample(sample_dir, taxonomy_path):
    """
    Extract MAG, contig and taxonomy information for specific sample.

    Parameters
    ----------
    sample_dir: str
        directory where to look for specific sample
    taxonomy_path: str
        path with taxonomy files

    Returns
    -------
    Pandas dataframe containing MAGS, contigs and taxonomies
    """
    mag_root = os.path.basename(sample_dir).rsplit("_")[0]
    taxonomy_files = glob.glob(os.path.join(taxonomy_path, f"{mag_root}*.tsv"))
    assert len(taxonomy_files) == 1, "Warning: multiple taxonomy files!"
    taxonomies_df = pd.read_csv(taxonomy_files[0], sep='\t',
                                usecols=["user_genome",
                                         "classification",
                                         "fastani_reference"])
    mags, bins, contigs = [], [], []
    # Run through all bin .fa files
    for bin_file in glob.glob(os.path.join(sample_dir, "*.fa")):
        bin_name = os.path.splitext(os.path.basename(bin_file))[0]
        mag_name = f"{mag_root}_{bin_name}"
        bin_contigs = load_fasta_ids(bin_file)
        mags.extend([mag_name]*len(bin_contigs))
        bins.extend([bin_name]*len(bin_contigs))
        contigs.extend(bin_contigs)
    # Construct dataframe
    raw_df = pd.DataFrame({"MAGS" : mags, "bins" : bins, "contigs" : contigs})
    # Add taxonomy information
    merged_df = raw_df.join(taxonomies_df.set_index('user_genome'), on='bins', how='left')
    return merged_df

def load_mags_contigs_taxonomies(bin_path, taxonomy_path):
    """
    # extract MAG, contig and taxonomy information for all samples.

    Parameters
    ----------
    bin_path: str
        path with samples
    taxonomy_path: str
        path with taxonomy files

    Returns
    -------
    Pandas dataframe containing MAGS, contigs and taxonomies
    """

    # Extract all sample directories
    bin_dirs = [f for f in os.scandir(bin_path) if f.is_dir()]

    # Return concatenated dataframe
    concatenated_df = pd.concat([load_mags_contigs_taxonomies_for_sample(bin_dir, taxonomy_path)
                      for bin_dir in bin_dirs],
                      ignore_index=True)
    return concatenated_df

@click.command()
@click.option('--genes_file', '-g', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to genes .fa file.')
@click.option('--cluster_file', '-r', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to cluster .txt file.')
@click.option('--contigs_file', '-c', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to contigs .fa file.')
@click.option('--eggnog_ann_file', '-e', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to eggnog .annotations file.')
@click.option('--bin_fp', '-b', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to bin folder.')
@click.option('--tax_fp', '-t', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=True),
              help='Input path to taxonomy folder.')
@click.option('--out_file', '-o', required=True,
              type=click.Path(resolve_path=True, readable=True, exists=False),
              help='Output .tsv file.')
def _perform_mapping(genes_file, cluster_file, contigs_file,
                     eggnog_ann_file, bin_fp, tax_fp, out_file):

    # Load contig and gene IDs
    contigs = load_fasta_ids(contigs_file)
    genes = load_fasta_ids(genes_file)

    # Cluster dataframe
    cluster_df = pd.read_csv(cluster_file, sep="\t",
                             names=['Cluster ID', 'Gene ID'])

    # Create gene catalogue dataframe
    genes_df = pd.DataFrame({'centroid': genes})
    genes_df = genes_df.astype(str)

    # Create contigs dataframe
    contigs_df = pd.DataFrame({'contigs_ID': contigs})
    contigs_df = contigs_df.astype(str)

    # map cluster and NR genes
    mapped_centroid_genes = pd.merge(cluster_df, genes_df,
                                     left_on='Gene ID',
                                     right_on='centroid',
                                     how='inner')[['Cluster ID', 'centroid']]

    # mapped cluster genes
    mapped_cluster_genes = pd.merge(cluster_df, mapped_centroid_genes,
                                    left_on='Cluster ID',
                                    right_on='Cluster ID',
                                    how='outer')

    # Create column with truncated centroid ids
    mapped_cluster_genes['centroid_trunc'] = mapped_cluster_genes['centroid'].\
    apply(lambda x: x.rsplit('_', 1)[0])

    # Change data type to string
    mapped_cluster_genes = mapped_cluster_genes.astype(str)

    # Map cluster genes to contigs
    mapped_genes_contigs = pd.merge(mapped_cluster_genes, contigs_df,
                                    left_on='centroid_trunc',
                                    right_on='contigs_ID',
                                    how='left')

    # MAGS and Taxonomy mapping
    MAGS_df = load_mags_contigs_taxonomies(bin_fp, tax_fp)

    # Mapping between genes, contigs and mags
    mapped_genes_contigs_mags = pd.merge(mapped_genes_contigs, MAGS_df,
                                         left_on='contigs_ID',
                                         right_on='contigs',
                                         how='outer')

    # Drop centroid_trunc column
    mapped_genes_contigs_mags = mapped_genes_contigs_mags.\
                                drop(columns="centroid_trunc")

    # Creating eggNOG annotation dataframe
    eggNOG_df = pd.read_csv(eggnog_ann_file, sep='\t', comment='#', skiprows=3)

    # Mapping between genes, contigs, mags and eggNOG annotations
    mapped_genes_contigs_mags_eggNOG = pd.merge(mapped_genes_contigs_mags,
                                                eggNOG_df,
                                                left_on='Gene ID',
                                                right_on='query_name',
                                                how='outer')

    # Saving results to file
    mapped_genes_contigs_mags_eggNOG.to_csv(out_file, sep='\t',
                                            index=False, na_rep='NaN')


if __name__ == "__main__":
    _perform_mapping()
