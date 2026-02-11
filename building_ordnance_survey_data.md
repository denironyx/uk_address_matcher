## Matching your messy addresses to authoratitive UK address data

Ordnance Survey is the UK’s authoritative provider of address data.  Many public sector organisations are able to use this data for free under the [Public Sector Geospatial Agreement](https://www.ordnancesurvey.co.uk/customers/public-sector/public-sector-geospatial-agreement) (PSGA).

This guide describes our recommended end-to-end process for address matching to Ordnance Survey data, including all software installs and building a single authorativie input address file file optimised for matching.

Supposing we have 100,000 messy addresses to match.  The steps and their respective timings are as follows.  Time taken dependes on whether the 100,000 are from around the whole country or a specific geographical region.  A local council area is used as an example.

| Task | Timing (Local council region) | Timing (Full country) |
|------|-------------------------------|----------------------|
| 1. Install Python and Astral UV and the `uk_address_matcher` package 5 minutes | 5 minutes |
| 2. Create a data package and corresponding API key in the [Ordnance Survey Data Hub](https://osdatahub.os.uk/data/downloads/data-packages) | 5 minutes | 5 minutes |
| 3. Process Ordnance Survey data into a flatfile | 5 seconds* | 4 minutes** |
| 4. Derives indexes and other features for address matching  | Not necessary, can be done on the fly | 4 mins 50 seconds |
| 5. Use `uk_address_matcher` to match 100,000 records | 26 seconds |  |

* Plus 15 seconds to download the data
** Plus 18 minutes to download the data

Timings data from processing on a Macbook Pro M4 Max.

Steps 1-3 are one-time-only jobs.  Subsequent data matching to the same geographic region only requires step 4.


## Step 1: Create a data package and obtain an API key

To download data from Ordnance Survey, you need three values:
- Data package `package_id`
- Its `version_id`; and
- An API key (the 'password' you use to download data)

Choose whether you want to use AddressBase or NGD.  Use whichever you're familiar with, but default to NGD if you've never used either.

Log in to `https://osdatahub.os.uk/` and create a [new receipie](https://osdatahub.os.uk/data/downloads/recipe-library) corresponding to the geographical area of interest.

Once created, navigate to [data packages](https://osdatahub.os.uk/data/downloads/data-packages/), and locate your data package, which will be at a URL like `https://osdatahub.os.uk/data/downloads/data-packages/18296`.

Use this URL to identify the data package ID, which in the above example is `18296`.  You also need the version id.  You can obtain this by hovering over any of the data downloads in the data packages.  The version ID is the number after the data package ID:

`https://osdatahub.os.uk/api/dataPackages/{data_package_id}/{version_id}/download?fileName=add_gb_builtaddress.zip`

Then obtain your API key and API secret from the [API Projects](https://osdatahub.os.uk/data/apis/projects) page in Data Hub.  Create a new project if one does not already exist.

## Step 2: Install the required software

We will use `uv` to install the `uk_address_matcher` package.  Install it using the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).

Create a new directory for your project, say `address_project`:

```bash
mkdir address_project
cd address_project
```


## Step 3: Build the optimised cannoical dataset of UK addresses

The instructions are slighly different depending on whether your chose a NGD data package or AddressBase Premium

### NGD:
```bash
git clone https://github.com/moj-analytical-services/prepare_ngd_for_address_matching

cd prepare_ngd_for_address_matching
```

### AddressBase Premium:
```bash
https://github.com/moj-analytical-services/prepare_addressbase_for_address_matching

cd prepare_addressbase_for_address_matching
```

Once you've cloned the builder you then need to populate the config files with your API key.

Create a new file called `.env`:

```
touch .env
```

Open the file, and add the following lines with the values you obtained in step 1.
```
OS_PROJECT_API_KEY=your_key_goes_here
OS_PROJECT_API_SECRET=your_secret_goes_here
```

Open the file called `config.yaml` and update the `package_id` and the `version_id` variables with the values you obtained in step 1.

Finally, in `config.yaml` update the `num_chunks` variable. This value causes the data to be processed in smaller parts rather than all at once, which means it runs more easily on a low specced compute.

If your data package is the full country, we recommend a value between about 20-50, depending on how powerful your laptop is.

If your data package is a single local authority, then a value of 1-4 is more appropriate.


Now you're ready to build the data:

```bash
uv sync
uv run python script.py
```

## Step 4: Match the data using `uk_daddre



Install `uk_address_matcher` into your project:
```
uv venv
uv pip install uk_address_matcher
```

Test it works:

Create a new file called `script.py`

```python
import uk_address_matcher
print("hello world")
```

And run it using:

```bash
uv run python my_script.py
```

## Step 3: